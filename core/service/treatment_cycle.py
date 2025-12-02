"""治疗疗程相关业务服务（Fat Service, Thin Views）。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from django.core.exceptions import ValidationError
from django.db import transaction

from core.models import TreatmentCycle
from core.models import choices
from users.models import PatientProfile


@transaction.atomic
def create_treatment_cycle(
    patient: PatientProfile,
    name: str,
    start_date: date,
    cycle_days: int = 21,
) -> TreatmentCycle:
    """
    【功能说明】
    - 为指定患者创建一个新的治疗疗程。
    - 自动计算计划结束日期，并校验与现有疗程的时间区间是否冲突。

    【参数说明】
    - patient: 患者档案对象 PatientProfile，表示疗程所属患者。
    - name: 疗程名称，例如“术后辅助治疗第一阶段”。
    - start_date: 疗程计划开始日期。
    - cycle_days: 周期天数，默认 21 天，用于推算计划结束日期。

    【返回参数说明】
    - 返回创建成功的 TreatmentCycle 实例；若时间区间与已有疗程冲突，会抛出 ValidationError。
    """

    if cycle_days <= 0:
        raise ValidationError("周期天数必须大于 0。")

    planned_end_date = start_date + timedelta(days=cycle_days - 1)

    conflict = (
        TreatmentCycle.objects.filter(patient=patient)
        .filter(start_date__lte=planned_end_date, end_date__gte=start_date)
        .filter(status=choices.TreatmentCycleStatus.IN_PROGRESS)
        .first()
    )
    if conflict:
        raise ValidationError(
            f"疗程时间与已有疗程冲突：{conflict.name} "
            f"({conflict.start_date} ~ {conflict.end_date})"
        )

    cycle = TreatmentCycle.objects.create(
        patient=patient,
        name=name,
        start_date=start_date,
        end_date=planned_end_date,
        cycle_days=cycle_days,
        status=choices.TreatmentCycleStatus.IN_PROGRESS,
    )
    return cycle


def terminate_treatment_cycle(cycle_id: int) -> TreatmentCycle:
    """
    【功能说明】
    - 提前强制终止一个正在进行中的疗程，不修改计划结束日期，仅更新状态。

    【参数说明】
    - cycle_id: 需要终止的 TreatmentCycle 主键 ID。

    【返回参数说明】
    - 返回更新后的 TreatmentCycle 实例；若状态不允许或已自然结束，会抛出 ValidationError。
    """

    try:
        cycle = TreatmentCycle.objects.get(pk=cycle_id)
    except TreatmentCycle.DoesNotExist as exc:
        raise ValidationError("疗程不存在。") from exc

    if cycle.status != choices.TreatmentCycleStatus.IN_PROGRESS:
        raise ValidationError("该疗程已结束或已终止，无需重复操作。")

    today = date.today()
    if cycle.end_date and today > cycle.end_date:
        raise ValidationError("该疗程已自然结束，无需手动终止。")

    cycle.status = choices.TreatmentCycleStatus.TERMINATED
    cycle.save(update_fields=["status"])

    # todo 终止后续，还需要处理这个疗程的计划。
    return cycle


def get_active_treatment_cycle(patient: PatientProfile) -> Optional[TreatmentCycle]:
    """
    【功能说明】
    - 查询患者当前时刻有效的治疗疗程（进行中且当前日期落在计划时间区间内）。

    【参数说明】
    - patient: 需要查询的患者档案对象 PatientProfile。

    【返回参数说明】
    - 若存在唯一有效疗程，返回该 TreatmentCycle 实例；
    - 若不存在符合条件的疗程，返回 None。
    """

    today = date.today()
    qs = TreatmentCycle.objects.filter(
        patient=patient,
        status=choices.TreatmentCycleStatus.IN_PROGRESS,
        start_date__lte=today,
        end_date__gte=today,
    ).order_by("-start_date")

    return qs.first()

