"""
接收来自设备回调的数据，并落库到 HealthMetric。

设计原则：
1. 视图层只做“验签 + 解析 JSON + 调用服务”，所有业务规则都集中在本模块。
2. 通过 deviceNo -> Device -> current_patient 找到患者，统一由这里决定是否落库。
3. 不同指标（血压 / 血氧 / 心率 / 步数 / 体重）通过统一入口分发到各自的保存方法。
4. 控制写入频率：
   - 步数：同一患者、同一天只保留一条记录，后续数据做累加。
   - 其他四类（血压、血氧、心率、体重）：同一患者、同一天最多写入 MAX_DAILY_RECORDS 条。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional

from django.utils import timezone

from business_support.models import Device
from health_data.models import HealthMetric, MetricType

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
            logger.info("收到未知 type=%s 的数据，暂不处理。payload=%s", metric_type, payload)

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

        HealthMetric.objects.create(
            patient_id=context.patient_id,
            task_id=None,
            metric_type=MetricType.BLOOD_PRESSURE,
            value_main=Decimal(str(sbp)),
            value_sub=Decimal(str(dbp)),
            measured_at=context.measured_at,
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

        HealthMetric.objects.create(
            patient_id=context.patient_id,
            task_id=None,
            metric_type=MetricType.BLOOD_OXYGEN,
            value_main=Decimal(str(avg_oxy)),
            value_sub=None,
            measured_at=context.measured_at,
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

        HealthMetric.objects.create(
            patient_id=context.patient_id,
            task_id=None,
            metric_type=MetricType.HEART_RATE,
            value_main=Decimal(str(heart_rate)),
            value_sub=None,
            measured_at=context.measured_at,
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
            HealthMetric.objects.create(
                patient_id=context.patient_id,
                task_id=None,
                metric_type=MetricType.STEPS,
                value_main=step_delta,
                value_sub=None,
                measured_at=context.measured_at,
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

        HealthMetric.objects.create(
            patient_id=context.patient_id,
            task_id=None,
            metric_type=MetricType.WEIGHT,
            value_main=weight,
            value_sub=None,
            measured_at=context.measured_at,
        )

    # ============
    # 工具方法
    # ============
    @classmethod
    def _build_context(cls, payload: dict) -> Optional[_Context]:
        """
        从回调 payload 中提取“患者 + 测量时间”的统一上下文。

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
        将设备上报的“北京时间毫秒时间戳”转换为带时区的 datetime。

        - 正常情况下：recordTime 为 Unix 毫秒时间戳，对应 Asia/Shanghai（当前时区）。
        - 异常或缺失时：回退为当前时间。
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
        """
        date = measured_at.date()
        count = HealthMetric.objects.filter(
            patient_id=patient_id,
            metric_type=metric_type,
            measured_at__date=date,
        ).count()
        return count < MAX_DAILY_RECORDS
