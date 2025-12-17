"""
接收来自设备回调的数据，并落库到 HealthMetric。

设计原则：
1. 视图层只做“验签 + 解析 JSON + 调用服务”，所有业务规则都集中在本模块。
2. 通过 deviceNo -> Device -> current_patient 找到患者，统一由这里决定是否落库。
3. 不同指标（血压 / 血氧 / 心率 / 步数 / 体重）通过统一入口分发到各自的保存方法。
4. 控制写入频率：
   - 步数：同一患者、同一天只保留一条记录，始终保留“当天最后一条上报记录”的步数。
   - 其他四类（血压、血氧、心率、体重）：同一患者、同一天最多写入 MAX_DAILY_RECORDS 条。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional

from django.apps import apps
from django.utils import timezone
from django.core.paginator import Paginator, Page

from business_support.models import Device
from health_data.models import METRIC_SCALES, HealthMetric, MetricSource, MetricType
from core.utils.sentinel import UNSET
import datetime

logger = logging.getLogger(__name__)

# 同一患者、同一指标类型、同一天最多允许写入的记录数
# （仅对“血压 / 血氧 / 心率 / 体重”生效；步数采用“单条累加”的特殊策略）
MAX_DAILY_RECORDS = 10


@dataclass(frozen=True)
class _Context:
    """
    从 payload 中解析出的、后续所有写入逻辑都依赖的上下文信息。

    - patient_id: 当前数据对应的患者 ID（通过 Device.current_patient 解析）。
    - measured_at: 测量发生时间（根据 recordTime 毫秒时间戳解析并转换到本地时区）。
    """

    patient_id: int
    measured_at: datetime


class HealthMetricService:
    @classmethod
    def handle_payload(cls, payload: dict) -> None:
        """
        统一入口：根据 type 分发到不同的指标保存方法。

        payload 结构示例：
        {
            "deviceNo": "...",
            "type": "BPG" / "WATCH" / "WS",
            "recordTime": 1765348624000,
            "bpgData": {...} / "watchData": {...} / "wsData": {...}
        }
        """
        metric_type = (payload.get("type") or "").upper()
        if not metric_type:
            logger.warning("回调数据缺少 type 字段: %s", payload)
            return

        # type 为设备侧业务编码：
        # - BPG   : 血压 + 心率
        # - WATCH : 可能包含血氧 / 步数 / 其他 WATCH 数据
        # - WS    : 体重
        if metric_type == "BPG":
            cls.save_blood_pressure(payload)
            cls.save_heart_rate(payload)
        elif metric_type == "WATCH":
            watch_data = payload.get("watchData") or {}
            if "spo" in watch_data:
                cls.save_blood_oxygen(payload)
            if "pedo" in watch_data:
                cls.save_steps(payload)
        elif metric_type == "WS":
            cls.save_weight(payload)
        else:
            logger.info(
                "收到未知 type=%s 的数据，暂不处理。payload=%s", metric_type, payload
            )

    # ============
    # 5 类指标保存
    # ============
    @classmethod
    def save_blood_pressure(cls, payload: dict) -> None:
        """
        保存血压数据。

        约定：
        - 主值 value_main 存收缩压（sbp）。
        - 副值 value_sub 存舒张压（dbp）。
        - 单个患者每天最多保存 MAX_DAILY_RECORDS 条血压记录。
        """
        context = cls._build_context(payload)
        if not context:
            return

        bpg_data = payload.get("bpgData") or {}
        sbp = bpg_data.get("sbp")
        dbp = bpg_data.get("dbp")
        if sbp is None or dbp is None:
            logger.warning("血压数据不完整，跳过。payload=%s", payload)
            return

        if not cls._can_store_today(
            context.patient_id, MetricType.BLOOD_PRESSURE, context.measured_at
        ):
            logger.info(
                "患者 %s 当天血压记录已达上限，丢弃本次数据。",
                context.patient_id,
            )
            return

        cls._persist_metric(
            patient_id=context.patient_id,
            metric_type=MetricType.BLOOD_PRESSURE,
            value_main=Decimal(str(sbp)),
            value_sub=Decimal(str(dbp)),
            measured_at=context.measured_at,
            source=MetricSource.DEVICE,
        )

    @classmethod
    def save_blood_oxygen(cls, payload: dict) -> None:
        """
        保存血氧数据。

        约定：
        - 主值 value_main 存平均血氧 agvOxy。
        - 不使用副值 value_sub。
        - 单个患者每天最多保存 MAX_DAILY_RECORDS 条血氧记录。
        """
        context = cls._build_context(payload)
        if not context:
            return

        watch_data = payload.get("watchData") or {}
        spo_data = watch_data.get("spo") or {}
        avg_oxy = spo_data.get("agvOxy")
        if avg_oxy is None:
            logger.warning("血氧数据不完整，跳过。payload=%s", payload)
            return

        if not cls._can_store_today(
            context.patient_id, MetricType.BLOOD_OXYGEN, context.measured_at
        ):
            logger.info(
                "患者 %s 当天血氧记录已达上限，丢弃本次数据。",
                context.patient_id,
            )
            return

        cls._persist_metric(
            patient_id=context.patient_id,
            metric_type=MetricType.BLOOD_OXYGEN,
            value_main=Decimal(str(avg_oxy)),
            measured_at=context.measured_at,
            source=MetricSource.DEVICE,
        )

    @classmethod
    def save_heart_rate(cls, payload: dict) -> None:
        """
        保存心率数据。

        可能来源：
        - BPG 包中的 bpgData.hr。
        - WATCH 包中的 watchData.hr（预留，视对接情况而定）。

        同一患者同一天最多保存 MAX_DAILY_RECORDS 条心率记录。
        """
        context = cls._build_context(payload)
        if not context:
            return

        bpg_data = payload.get("bpgData") or {}
        watch_data = payload.get("watchData") or {}
        heart_rate = bpg_data.get("hr") or watch_data.get("hr")
        if heart_rate is None:
            # 心率缺失不算错误，静默跳过即可
            return

        if not cls._can_store_today(
            context.patient_id, MetricType.HEART_RATE, context.measured_at
        ):
            logger.info(
                "患者 %s 当天心率记录已达上限，丢弃本次数据。",
                context.patient_id,
            )
            return

        cls._persist_metric(
            patient_id=context.patient_id,
            metric_type=MetricType.HEART_RATE,
            value_main=Decimal(str(heart_rate)),
            measured_at=context.measured_at,
            source=MetricSource.DEVICE,
        )

    @classmethod
    def save_steps(cls, payload: dict) -> None:
        """
        步数：一天只保留一条记录，记录“当日累计步数”。

        约定：
        - 客户端上传的 step 已经是“当日累计步数”。
        - 主值 value_main 存“当日累计步数”，每次回调覆盖当天最后一条记录的步数。
        - 不使用副值 value_sub。
        - 若当天已有记录：只更新“最新一条记录”的 value_main 与 measured_at，不新增记录。
        """
        context = cls._build_context(payload)
        if not context:
            return

        watch_data = payload.get("watchData") or {}
        pedo_data = watch_data.get("pedo") or {}
        steps = pedo_data.get("step")
        if steps is None:
            logger.warning("步数数据不完整，跳过。payload=%s", payload)
            return

        try:
            step_delta = Decimal(str(steps))
        except Exception:  # noqa: BLE001
            logger.warning("步数数据格式错误，跳过。payload=%s", payload)
            return

        date = context.measured_at.date()
        metric = (
            HealthMetric.objects.filter(
                patient_id=context.patient_id,
                metric_type=MetricType.STEPS,
                measured_at__date=date,
            )
            .order_by("-measured_at")
            .first()
        )

        if metric:
            # 当天已有记录：覆盖为当前上报的“当日累计步数”
            metric.value_main = step_delta
            metric.measured_at = context.measured_at
            metric.save(update_fields=["value_main", "measured_at"])
        else:
            cls._persist_metric(
                patient_id=context.patient_id,
                metric_type=MetricType.STEPS,
                value_main=step_delta,
                measured_at=context.measured_at,
                source=MetricSource.DEVICE,
            )

    @classmethod
    def save_weight(cls, payload: dict) -> None:
        """
        保存体重数据。

        约定：
        - 设备上传的 weight 通常为放大 100 倍的整数，例如 6830 -> 68.30 kg。
        - 主值 value_main 存换算后的 kg 数值。
        - 不使用副值 value_sub。
        - 同一患者同一天最多保存 MAX_DAILY_RECORDS 条体重记录。
        """
        context = cls._build_context(payload)
        if not context:
            return

        ws_data = payload.get("wsData") or {}
        weight_raw = ws_data.get("weight")
        if weight_raw is None:
            logger.warning("体重数据不完整，跳过。payload=%s", payload)
            return

        try:
            # 示例：6830 -> 68.30 kg
            weight = Decimal(str(weight_raw)) / Decimal("100")
        except Exception:  # noqa: BLE001
            logger.warning("体重数据格式错误，跳过。payload=%s", payload)
            return

        if not cls._can_store_today(
            context.patient_id, MetricType.WEIGHT, context.measured_at
        ):
            logger.info(
                "患者 %s 当天体重记录已达上限，丢弃本次数据。",
                context.patient_id,
            )
            return

        cls._persist_metric(
            patient_id=context.patient_id,
            metric_type=MetricType.WEIGHT,
            value_main=weight,
            measured_at=context.measured_at,
            source=MetricSource.DEVICE,
        )

    
    @classmethod
    def query_metrics_by_type(
        cls,
        patient_id: int,
        metric_type: str,
        *,
        page: int = 1,
        page_size: int = 10,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        sort_order: str = "desc",
    ) -> Page:
        """
        分页查询指定患者、指定类型的健康指标记录（返回 Page[HealthMetric]）。

        【功能说明】
        - 按条件查询 HealthMetric 记录，并按时间排序后进行分页。
        - 返回 Django 的 Page 对象，page.object_list 中是当前页的 HealthMetric 实例列表。
        - 展示层可以使用 `metric.display_value` 获取前端友好的展示文案。

        【参数说明】
        :param patient_id: 患者 ID。
        :param metric_type: 指标类型枚举值（如 MetricType.BLOOD_PRESSURE）。
        :param page: 页码，从 1 开始，默认 1。
        :param page_size: 每页数量，默认 10；为防止单页过大，最大限制为 100。
        :param start_date: 起始时间（包含），用于按测量时间过滤。
        :param end_date: 结束时间（不包含），用于按测量时间过滤。
        :param sort_order: 排序方式，"asc" 或 "desc"，按 measured_at 字段排序。

        【返回值】
        :return: Django Page 对象：
            - page.object_list: 当前页的 HealthMetric 实例列表。
            - page.paginator.count: 总记录数。
            - page.paginator.num_pages: 总页数。
            - page.number: 当前页码。

        【使用示例】
        在 View / Serializer 中：

        >>> page = HealthMetricService.query_metrics_by_type(
        ...     patient_id=1,
        ...     metric_type=MetricType.BLOOD_PRESSURE,
        ...     page=1,
        ...     page_size=10,
        ... )
        >>> total = page.paginator.count       # 总记录数
        >>> current_page = page.number         # 当前页码
        >>> items = []
        >>> for metric in page.object_list:
        ...     items.append({
        ...         "id": metric.id,
        ...         "type": metric.metric_type,
        ...         "value_main": metric.value_main,
        ...         "value_sub": metric.value_sub,
        ...         "value_display": metric.display_value,  # 使用 model 的展示属性
        ...         "measured_at": metric.measured_at,
        ...         "source": metric.source,
        ...     })
        >>>
        >>> response_data = {
        ...     "total": total,
        ...     "page": current_page,
        ...     "page_size": page.paginator.per_page,
        ...     "results": items,
        ... }

        通过这种方式，Service 层只负责提供分页后的对象列表，
        JSON 结构和字段选择由 View/Serializer 决定。
        """
        # 1. 校验排序参数
        if sort_order not in ("asc", "desc"):
            raise ValueError('sort_order must be "asc" or "desc"')

        # 2. 每页数量上限，防止单页数据量过大
        page_size = min(page_size, 100)

        # 3. 查询数据库
        qs = HealthMetric.objects.filter(
            patient_id=patient_id, metric_type=metric_type
        )

        if start_date:
            qs = qs.filter(measured_at__gte=start_date)
        if end_date:
            qs = qs.filter(measured_at__lt=end_date)

        # 排序
        order_field = "measured_at" if sort_order == "asc" else "-measured_at"
        qs = qs.order_by(order_field)

        # 4. 使用 Django Paginator 分页
        paginator = Paginator(qs, page_size)
        page_obj = paginator.page(page)
        return page_obj

    # ============
    # 查询用户上一条数据记录
    # patient_id 必填， patient_id 无效直接出异常
    # metric_type： 可以为空， 为空则查询所有特征的最后一条记录
    # 返回值是一个字典， 说明每一个指标类型名称， 值（两个）， 上传时间， 以及source
    # ============
    @classmethod
    def query_last_metric(cls, patient_id: int, metric_type: str | None = None) -> dict:
        """
        查询指定患者的最新健康指标数据。

        【功能说明】
        获取患者各项指标（或指定指标）的最后一条记录。
        常用于前端展示“患者最新状态”卡片或图表上方的当前值。

        【参数】
        :param patient_id: 患者 ID。如果 ID 不存在，将抛出 PatientProfile.DoesNotExist 异常。
        :param metric_type: (可选) 指定查询的指标类型。
                            - None: 查询所有指标类型的最新记录。
                            - str: 仅查询指定类型的最新记录（如 MetricType.BLOOD_PRESSURE）。

        【返回值】
        返回一个字典，Key 为指标类型（如 'blood_pressure'），Value 为数据详情字典或 None。
        示例：
        {
            "blood_pressure": {
                "name": "血压",
                "value_main": 120.00,
                "value_sub": 80.00,
                "value_display": "120/80",
                "measured_at": datetime(...),
                "source": "device"
            },
            "sputum_color": None,  # 该指标无数据
            ...
        }
        """
        # 1. 校验患者是否存在
        # 使用 apps.get_model 避免循环导入
        PatientProfile = apps.get_model("users", "PatientProfile")
        if not PatientProfile.objects.filter(id=patient_id).exists():
            raise PatientProfile.DoesNotExist(f"Patient {patient_id} does not exist")

        # 2. 确定需要查询的指标类型列表
        target_types = [metric_type] if metric_type else MetricType.values

        result = {}

        # 3. 遍历查询（方案一：简单循环查询，保证逻辑清晰且绝对最新）
        for m_type in target_types:
            metric = (
                HealthMetric.objects.filter(patient_id=patient_id, metric_type=m_type)
                .order_by("-measured_at")
                .first()
            )

            if not metric:
                result[m_type] = None
                continue

            result[m_type] = {
                "name": MetricType(m_type).label,
                "value_main": metric.value_main,
                "value_sub": metric.value_sub,
                "value_display": cls._format_display_value(metric),
                "measured_at": metric.measured_at,
                "source": metric.source,
            }

        return result

    # ============
    # 客观指标数据手动录入接口
    # ============
    @classmethod
    def save_manual_metric(
        cls,
        patient_id: int,
        metric_type: str,
        measured_at: datetime,
        value_main: Optional[Decimal] = None,
        value_sub: Optional[Decimal] = None,
    ) -> HealthMetric:
        """
        手动录入健康指标数据的通用入口。

        【功能说明】
        该方法供 View 层调用，用于保存用户手动填写的各类健康数据（如体能评分、疼痛评分、痰色等）。
        与设备自动上传不同，手动录入的数据不做“每日条数限制”，每次调用都会生成一条新记录。
        数据来源（source）会自动标记为 MANUAL。

        【参数解释】
        :param patient_id: int
            患者 ID（对应 PatientProfile.id）。
        :param metric_type: str
            指标类型枚举值。
            必须使用 health_data.models.MetricType 中的常量，例如：
            - MetricType.PHYSICAL_PERFORMANCE ("physical_performance")
            - MetricType.SPUTUM_COLOR ("sputum_color")
            - MetricType.PAIN_HEAD ("pain_head")
        :param measured_at: datetime
            测量时间（带时区）。通常由前端传入用户选择的时间。
        :param value_main: Optional[Decimal]
            主数值。
            - 对于数值型指标（如体重），直接存入。
            - 对于评分/枚举型指标（如痰色、疼痛等级），存入对应的分值（整数转 Decimal）。
              具体分值定义请参考 health_data.models.METRIC_SCALES 字典。
        :param value_sub: Optional[Decimal]
            副数值。
            - 目前主要用于血压（舒张压），其他指标通常留空（None）。

        【返回值】
        :return: HealthMetric
            创建成功的数据库模型实例。

        【成功与失败】
        - 成功：返回 HealthMetric 对象，表示数据已成功写入数据库。
        - 失败：
            1. 如果参数类型错误（如 Decimal 转换失败），Python 会抛出 TypeError 或 InvalidOperation。
            2. 如果数据库约束失败（如 patient_id 不存在），会抛出 IntegrityError。
            View 层应当捕获这些异常，或者在调用前确保数据格式正确。
        """
        return cls._persist_metric(
            patient_id=patient_id,
            metric_type=metric_type,
            value_main=value_main,
            value_sub=value_sub,
            measured_at=measured_at,
            source=MetricSource.MANUAL,
        )

    # ============
    # 客观指标数据更新 / 删除接口（主要面向手动录入数据）
    # ============
    @classmethod
    def update_manual_metric(
        cls,
        metric_id: int,
        *,
        value_main=UNSET,
        value_sub=UNSET,
        measured_at=UNSET,
    ) -> HealthMetric:
        """
        更新一条“手动录入”的健康指标记录。

        【功能说明】
        - 仅允许修改来源为 MANUAL 的记录（source = MetricSource.MANUAL）。
        - 参数为可选更新：
          - 不传某个参数：表示“不修改该字段”；
          - 显式传 None：表示将该字段更新为 NULL。
        - 只会对 is_active=True 的有效记录生效（软删除的数据不会被更新）。

        【参数说明】
        :param metric_id: 待更新的 HealthMetric 记录 ID。
        :param value_main: (可选) 新的主数值；不传则不更新。
        :param value_sub: (可选) 新的副数值；不传则不更新。
        :param measured_at: (可选) 新的测量时间；不传则不更新。

        【返回值】
        :return: 更新后的 HealthMetric 实例。

        【错误情况】
        - 若记录不存在（或已被软删除）：会抛出 HealthMetric.DoesNotExist 异常。
        - 若记录来源为设备数据（source != MANUAL）：抛出 ValueError。

        【使用示例】
        >>> metric = HealthMetricService.update_manual_metric(
        ...     metric_id=1,
        ...     value_main=Decimal("37.5"),
        ... )
        >>> metric.display_value
        '37.5 °C'
        """
        metric = HealthMetric.objects.get(id=metric_id)

        if metric.source != MetricSource.MANUAL:
            raise ValueError("只能修改手动录入的健康指标记录")

        fields_to_update: list[str] = []

        if value_main is not UNSET:
            metric.value_main = value_main
            fields_to_update.append("value_main")

        if value_sub is not UNSET:
            metric.value_sub = value_sub
            fields_to_update.append("value_sub")

        if measured_at is not UNSET:
            metric.measured_at = measured_at
            fields_to_update.append("measured_at")

        if fields_to_update:
            metric.save(update_fields=fields_to_update)

        return metric

    @classmethod
    def delete_metric(cls, metric_id: int) -> HealthMetric:
        """
        软删除一条健康指标记录：仅将 is_active 标记为 False，不做物理删除。

        【功能说明】
        - 只对当前仍为有效状态的记录生效（is_active=True）。
        - 删除后，通过默认的 HealthMetric.objects 将无法再查询到该记录；
          如需包含软删除记录，请使用 HealthMetric.all_objects。

        【参数说明】
        :param metric_id: 待删除的 HealthMetric 记录 ID。

        【返回值】
        :return: 刚被标记为无效的 HealthMetric 实例。

        【错误情况】
        - 若记录不存在（或已被软删除）：会抛出 HealthMetric.DoesNotExist 异常。
        """
        metric = HealthMetric.objects.get(id=metric_id)
        metric.is_active = False
        metric.save(update_fields=["is_active"])
        return metric

    # ============
    # 内部持久化
    # ============
    @staticmethod
    def _persist_metric(
        patient_id: int,
        metric_type: str,
        measured_at: datetime,
        source: str,
        value_main: Optional[Decimal] = None,
        value_sub: Optional[Decimal] = None,
    ) -> HealthMetric:
        return HealthMetric.objects.create(
            patient_id=patient_id,
            metric_type=metric_type,
            source=source,
            value_main=value_main,
            value_sub=value_sub,
            measured_at=measured_at,
        )

    # ============
    # 工具方法
    # ============
    @classmethod
    def _build_context(cls, payload: dict) -> Optional[_Context]:
        """
        从回调 payload 中提取“患者 + 测量时间”的统一上下文。
        这里接收的数据来自设备

        - 根据 deviceNo 查找 Device（优先当作 imei，其次尝试 sn）。
        - 使用 Device.current_patient 作为最终关联患者；
          若设备不存在或未绑定患者，则直接忽略本条数据。
        - 使用 recordTime 毫秒时间戳解析 measured_at。
        """
        device_no = payload.get("deviceNo")
        record_time = payload.get("recordTime")

        if not device_no:
            logger.warning("回调数据缺少 deviceNo，跳过。payload=%s", payload)
            return None

        device = (
            Device.objects.select_related("current_patient")
            .filter(imei=device_no)
            .first()
        ) or (
            Device.objects.select_related("current_patient")
            .filter(sn=device_no)
            .first()
        )

        if not device:
            logger.warning("未找到匹配设备 deviceNo=%s，跳过。", device_no)
            return None

        if not device.current_patient_id:
            logger.info("设备 %s 未绑定患者，跳过数据。", device.pk)
            return None

        measured_at = cls._parse_measured_at(record_time)
        return _Context(patient_id=device.current_patient_id, measured_at=measured_at)

    @staticmethod
    def _parse_measured_at(record_time) -> datetime:
        """
        将设备上报的毫秒时间戳转换为带时区的 datetime。
        这里接收的数据来自设备

        - 正常情况下：recordTime 为 Unix 毫秒时间戳（设备上报时间，不带时区信息），
          这里按当前 Django 时区（TIME_ZONE = Asia/Shanghai）进行解析。
        - 由于 USE_TZ = True，落库时会自动转换为 UTC，因此直接看数据库原始值时，
          会比北京时间小 8 小时，这是预期行为。
        - 异常或缺失 recordTime 时：回退为当前时间。
        """
        if record_time is None:
            return timezone.now()
        try:
            timestamp = int(record_time) / 1000.0
            # 设备上传的是“北京时间”，直接按当前时区解释即可
            tz = timezone.get_current_timezone()
            dt = datetime.fromtimestamp(timestamp, tz=tz)
            return dt
        except Exception:  # noqa: BLE001
            return timezone.now()

    @staticmethod
    def _can_store_today(
        patient_id: int, metric_type: str, measured_at: datetime
    ) -> bool:
        """
        判断在“患者 + 指标类型 + 日期”维度上，是否允许继续写入新记录。

        步数不走这个限制，而是通过 save_steps 的“当日单条累加”策略控制。

        这里接收的数据来自设备
        """
        date = measured_at.date()
        count = HealthMetric.objects.filter(
            patient_id=patient_id,
            metric_type=metric_type,
            measured_at__date=date,
        ).count()
        return count < MAX_DAILY_RECORDS

    @staticmethod
    def _format_display_value(metric: HealthMetric) -> str:
        """
        根据指标类型，将数值格式化为前端友好的展示字符串。
        """
        m_type = metric.metric_type
        val_main = metric.value_main
        val_sub = metric.value_sub

        if val_main is None:
            return ""

        # 1. 优先处理枚举/评分映射 (如痰色、疼痛、ECOG)
        # 交由 HealthMetric 实例自身的 display_value 属性处理
        return metric.display_value
