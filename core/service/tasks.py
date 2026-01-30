"""患者端计划与任务状态服务。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List

from django.db import models
from django.utils import timezone

from core.models import DailyTask, MonitoringTemplate, choices
from health_data.models import MetricType
from users.models import PatientProfile


_SUMMARY_TITLE_BY_TYPE = {
    choices.PlanItemCategory.MEDICATION: "用药提醒",
    choices.PlanItemCategory.CHECKUP: "复查提醒",
    choices.PlanItemCategory.QUESTIONNAIRE: "问卷提醒",
}

MONITORING_ADHERENCE_ALL = "MONITORING_ALL"
MONITORING_ADHERENCE_TYPES = (
    MetricType.BLOOD_PRESSURE,
    MetricType.BLOOD_OXYGEN,
    MetricType.HEART_RATE,
    MetricType.STEPS,
    MetricType.WEIGHT,
    MetricType.BODY_TEMPERATURE,
)

_TASK_MAX_OVERDUE_DAYS = {
    choices.PlanItemCategory.MEDICATION: 0,
    choices.PlanItemCategory.MONITORING: 0,
    choices.PlanItemCategory.CHECKUP: 7,
    choices.PlanItemCategory.QUESTIONNAIRE: 7,
}




# TODO 查询复查档案的记录数（需要支持到二级分类）。
# TODO 根据日期来查询复查的图像。  

def get_daily_plan_summary(
    patient: PatientProfile,
    task_date: date = date.today(),
) -> List[Dict[str, Any]]:
    """
    【功能说明】
    - 汇总患者当天及有效期内的计划任务，用于患者端列表展示。
      - 用药/监测：仅统计当天。
      - 复查/问卷：统计最近 7 天内任务。

    【使用方法】
    - `get_daily_plan_summary(patient)` 返回今天的计划摘要；
    - `get_daily_plan_summary(patient, date(2025, 1, 1))` 返回指定日期摘要。

    【参数说明】
    - patient: PatientProfile，当前患者。
    - task_date: date，默认为当天。

    【返回值说明】
    - List[dict]，结构示例：
      [{"task_type": 1, "status": 0, "title": "用药提醒"}]
      问卷类型会额外返回 questionnaire_ids（具体问卷 ID 列表）。
    """

    task_types = (
        choices.PlanItemCategory.MEDICATION,
        choices.PlanItemCategory.CHECKUP,
        choices.PlanItemCategory.QUESTIONNAIRE,
        choices.PlanItemCategory.MONITORING,
    )

    refresh_task_statuses(as_of_date=task_date, patient_id=patient.id)

    window_start_by_type = {
        choices.PlanItemCategory.MEDICATION: task_date,
        choices.PlanItemCategory.MONITORING: task_date,
        choices.PlanItemCategory.CHECKUP: task_date
        - timedelta(days=_TASK_MAX_OVERDUE_DAYS[choices.PlanItemCategory.CHECKUP]),
        choices.PlanItemCategory.QUESTIONNAIRE: task_date
        - timedelta(days=_TASK_MAX_OVERDUE_DAYS[choices.PlanItemCategory.QUESTIONNAIRE]),
    }
    min_window_start = min(window_start_by_type.values())

    tasks = (
        DailyTask.objects.filter(
            patient=patient,
            task_date__range=(min_window_start, task_date),
            task_type__in=task_types,
        )
        .exclude(
            status__in=[
                choices.TaskStatus.NOT_STARTED,
                choices.TaskStatus.TERMINATED,
            ]
        )
        .select_related("plan_item")
        .order_by("task_date", "id")
    )

    # 按类型聚合任务，便于后续做“合并/逐条”逻辑。
    tasks_by_type = {task_type: [] for task_type in task_types}
    for task in tasks:
        window_start = window_start_by_type.get(task.task_type, task_date)
        if task.task_date < window_start:
            continue
        tasks_by_type[task.task_type].append(task)

    summary: List[Dict[str, Any]] = []
    # 用药/复查/问卷：每类只保留一条摘要。
    for task_type in (
        choices.PlanItemCategory.MEDICATION,
        choices.PlanItemCategory.CHECKUP,
        choices.PlanItemCategory.QUESTIONNAIRE,
    ):
        task_list = tasks_by_type[task_type]
        if not task_list:
            continue
        task_list.sort(
            key=lambda task: (
                0 if task.status == choices.TaskStatus.PENDING else 1,
                task.task_date,
                task.id,
            )
        )
        questionnaire_ids = []
        if task_type == choices.PlanItemCategory.QUESTIONNAIRE:
            seen = set()
            for task in task_list:
                if not task.plan_item_id:
                    continue
                questionnaire_id = task.plan_item.template_id
                if questionnaire_id in seen:
                    continue
                seen.add(questionnaire_id)
                questionnaire_ids.append(questionnaire_id)
        summary.append(
            {
                "task_type": int(task_type),
                "status": int(task_list[0].status),
                "title": _SUMMARY_TITLE_BY_TYPE[task_type],
                **(
                    {"questionnaire_ids": questionnaire_ids}
                    if task_type == choices.PlanItemCategory.QUESTIONNAIRE
                    else {}
                ),
            }
        )

    # 监测：逐条返回（前端需逐项展示）。
    for task in tasks_by_type[choices.PlanItemCategory.MONITORING]:
        summary.append(
            {
                "task_type": int(task.task_type),
                "status": int(task.status),
                "title": task.title,
            }
        )

    return summary


def _get_task_max_overdue_days(task_type: int) -> int:
    return _TASK_MAX_OVERDUE_DAYS.get(task_type, 0)


def resolve_task_valid_window(
    *,
    task_type: int,
    as_of_date: date,
) -> tuple[date, date]:
    max_overdue_days = _get_task_max_overdue_days(task_type)
    window_start = as_of_date - timedelta(days=max_overdue_days)
    return window_start, as_of_date


def resolve_task_status(
    *,
    task_type: int,
    task_date: date,
    as_of_date: date,
) -> int:
    if task_date > as_of_date:
        return choices.TaskStatus.NOT_STARTED
    window_start, _ = resolve_task_valid_window(
        task_type=task_type,
        as_of_date=as_of_date,
    )
    if task_date < window_start:
        return choices.TaskStatus.TERMINATED
    return choices.TaskStatus.PENDING


def refresh_task_statuses(
    *,
    as_of_date: date | None = None,
    patient_id: int | None = None,
) -> int:
    """
    【功能说明】
    - 按任务类型与有效期刷新任务状态。

    【规则说明】
    - task_date > as_of_date：未开始。
    - task_date <= as_of_date 且超出有效期：已终止。
    - task_date <= as_of_date 且在有效期内：未完成。
    - 已完成任务保持不变。
    """
    if as_of_date is None:
        as_of_date = timezone.localdate()

    base_qs = DailyTask.objects.exclude(status=choices.TaskStatus.COMPLETED)
    if patient_id is not None:
        base_qs = base_qs.filter(patient_id=patient_id)

    updated = 0
    for task_type, max_overdue_days in _TASK_MAX_OVERDUE_DAYS.items():
        type_qs = base_qs.filter(task_type=task_type)
        expired_before = as_of_date - timedelta(days=max_overdue_days)

        updated += (
            type_qs.filter(task_date__gt=as_of_date)
            .exclude(status=choices.TaskStatus.NOT_STARTED)
            .update(status=choices.TaskStatus.NOT_STARTED)
        )
        updated += (
            type_qs.filter(task_date__lt=expired_before)
            .exclude(status=choices.TaskStatus.TERMINATED)
            .update(status=choices.TaskStatus.TERMINATED)
        )
        updated += (
            type_qs.filter(task_date__gte=expired_before, task_date__lte=as_of_date)
            .exclude(status=choices.TaskStatus.PENDING)
            .update(status=choices.TaskStatus.PENDING)
        )

    return updated


def _resolve_task_date(occurred_at: datetime | None) -> date:
    """
    【功能说明】
    - 将事件发生时间转换为任务日期，用于筛选当日任务。

    【使用方法】
    - `_resolve_task_date(measured_at)`。

    【参数说明】
    - occurred_at: datetime | None，事件时间；为空则使用当前时间。

    【返回值说明】
    - date，对应任务日期。
    """
    if occurred_at is None:
        return timezone.localdate()
    if timezone.is_naive(occurred_at):
        return occurred_at.date()
    return timezone.localtime(occurred_at).date()


def _resolve_completed_at(occurred_at: datetime | None) -> datetime:
    """
    【功能说明】
    - 统一任务完成时间字段；若未提供则使用当前时间。

    【使用方法】
    - `_resolve_completed_at(measured_at)`。

    【参数说明】
    - occurred_at: datetime | None，事件时间。

    【返回值说明】
    - datetime，用于写入 completed_at。
    """
    return occurred_at or timezone.now()


def _resolve_latest_incomplete_task_date(
    *,
    patient_id: int,
    task_type: int,
    completed_at: datetime,
) -> date | None:
    task_date = _resolve_task_date(completed_at)
    window_start, window_end = resolve_task_valid_window(
        task_type=task_type,
        as_of_date=task_date,
    )
    candidate = (
        DailyTask.objects.filter(
            patient_id=patient_id,
            task_type=task_type,
            task_date__range=(window_start, window_end),
            status__in=[
                choices.TaskStatus.PENDING,
                choices.TaskStatus.NOT_STARTED,
            ],
        )
        .order_by("-task_date", "-id")
        .values_list("task_date", flat=True)
        .first()
    )
    return candidate


def complete_daily_medication_tasks(
    patient_id: int,
    occurred_at: datetime | None = None,
) -> int | None:
    """
    【功能说明】
    - 将患者当天所有“用药任务”标记为已完成。

    【使用方法】
    - `complete_daily_medication_tasks(patient_id, measured_at)`。

    【参数说明】
    - patient_id: int，患者 ID。
    - occurred_at: datetime | None，事件时间，用于定位当日任务及 completed_at。

    【返回值说明】
    - int | None：返回第一条匹配任务的 ID；若无任务则返回 None。
    """
    refresh_task_statuses(as_of_date=timezone.localdate(), patient_id=patient_id)
    completed_at = _resolve_completed_at(occurred_at)
    task_date = _resolve_task_date(completed_at)

    tasks = DailyTask.objects.filter(
        patient_id=patient_id,
        task_date=task_date,
        task_type=choices.PlanItemCategory.MEDICATION,
        status__in=[
            choices.TaskStatus.PENDING,
            choices.TaskStatus.NOT_STARTED,
            choices.TaskStatus.TERMINATED,
        ],
    )
    task_id = tasks.values_list("id", flat=True).first()
    tasks.update(
        status=choices.TaskStatus.COMPLETED,
        completed_at=completed_at,
    )
    return task_id


def _get_monitoring_tasks_queryset(
    *,
    patient_id: int,
    metric_type: str,
    occurred_at: datetime | None,
) -> tuple[models.QuerySet, datetime]:
    completed_at = _resolve_completed_at(occurred_at)
    task_date = _resolve_task_date(completed_at)

    template_ids = list(
        MonitoringTemplate.objects.filter(code=metric_type).values_list("id", flat=True)
    )
    if not template_ids:
        return DailyTask.objects.none(), completed_at

    tasks = DailyTask.objects.filter(
        patient_id=patient_id,
        task_date=task_date,
        task_type=choices.PlanItemCategory.MONITORING,
        plan_item__template_id__in=template_ids,
    )
    return tasks, completed_at


def complete_daily_monitoring_tasks(
    patient_id: int,
    metric_type: str,
    occurred_at: datetime | None = None,
) -> int:
    """
    【功能说明】
    - 将患者当天指定监测项的任务标记为已完成（覆盖当日所有匹配任务）。

    【使用方法】
    - `complete_daily_monitoring_tasks(patient_id, MetricType.BODY_TEMPERATURE, measured_at)`。

    【参数说明】
    - patient_id: int，患者 ID。
    - metric_type: str，健康指标类型（对应 MonitoringTemplate.code）。
    - occurred_at: datetime | None，事件时间，用于定位当日任务及 completed_at。

    【返回值说明】
    - int：实际更新的任务数量。
    """
    refresh_task_statuses(as_of_date=timezone.localdate(), patient_id=patient_id)
    tasks, completed_at = _get_monitoring_tasks_queryset(
        patient_id=patient_id,
        metric_type=metric_type,
        occurred_at=occurred_at,
    )
    return tasks.filter(
        status__in=[
            choices.TaskStatus.PENDING,
            choices.TaskStatus.NOT_STARTED,
            choices.TaskStatus.TERMINATED,
        ]
    ).update(status=choices.TaskStatus.COMPLETED, completed_at=completed_at)


def complete_daily_monitoring_tasks_with_latest_task_id(
    patient_id: int,
    metric_type: str,
    occurred_at: datetime | None = None,
) -> tuple[int, int | None]:
    """
    【功能说明】
    - 将患者当天指定监测项的任务标记为已完成，并返回最新任务 ID。

    【使用方法】
    - `complete_daily_monitoring_tasks_with_latest_task_id(patient_id, MetricType.BODY_TEMPERATURE, measured_at)`。

    【参数说明】
    - patient_id: int，患者 ID。
    - metric_type: str，健康指标类型（对应 MonitoringTemplate.code）。
    - occurred_at: datetime | None，事件时间，用于定位当日任务及 completed_at。

    【返回值说明】
    - (updated_count, task_id)：updated_count 为更新数量；task_id 为最新任务 ID（无匹配任务则为 None）。
    """
    refresh_task_statuses(as_of_date=timezone.localdate(), patient_id=patient_id)
    tasks, completed_at = _get_monitoring_tasks_queryset(
        patient_id=patient_id,
        metric_type=metric_type,
        occurred_at=occurred_at,
    )
    latest_task_id = tasks.order_by("-id").values_list("id", flat=True).first()
    updated_count = tasks.filter(
        status__in=[
            choices.TaskStatus.PENDING,
            choices.TaskStatus.NOT_STARTED,
            choices.TaskStatus.TERMINATED,
        ]
    ).update(status=choices.TaskStatus.COMPLETED, completed_at=completed_at)
    return updated_count, latest_task_id


def complete_daily_questionnaire_tasks(
    patient_id: int,
    occurred_at: datetime | None = None,
) -> tuple[int, int | None]:
    """
    【功能说明】
    - 将患者当天的问卷任务标记为已完成。

    【使用方法】
    - `complete_daily_questionnaire_tasks(patient_id, submitted_at)`。

    【参数说明】
    - patient_id: int，患者 ID。
    - occurred_at: datetime | None，事件时间，用于定位当日任务及 completed_at。

    【返回值说明】
    - (updated_count, task_id)：updated_count 为更新数量；task_id 为匹配的首条任务 ID（无匹配任务则为 None）。
    """
    refresh_task_statuses(as_of_date=timezone.localdate(), patient_id=patient_id)
    completed_at = _resolve_completed_at(occurred_at)
    target_date = _resolve_latest_incomplete_task_date(
        patient_id=patient_id,
        task_type=choices.PlanItemCategory.QUESTIONNAIRE,
        completed_at=completed_at,
    )
    if not target_date:
        return 0, None

    tasks = DailyTask.objects.filter(
        patient_id=patient_id,
        task_date=target_date,
        task_type=choices.PlanItemCategory.QUESTIONNAIRE,
        status__in=[
            choices.TaskStatus.PENDING,
            choices.TaskStatus.NOT_STARTED,
        ],
    )
    task_id = tasks.order_by("id").values_list("id", flat=True).first()
    updated_count = tasks.update(
        status=choices.TaskStatus.COMPLETED,
        completed_at=completed_at,
    )
    return updated_count, task_id


def complete_daily_checkup_tasks(
    patient_id: int,
    occurred_at: datetime | None = None,
) -> int:
    """
    【功能说明】
    - 将患者当天的复查任务标记为已完成。

    【使用方法】
    - `complete_daily_checkup_tasks(patient_id, uploaded_at)`。

    【参数说明】
    - patient_id: int，患者 ID。
    - occurred_at: datetime | None，事件时间，用于定位当日任务及 completed_at。

    【返回值说明】
    - int：实际更新的任务数量。
    """
    refresh_task_statuses(as_of_date=timezone.localdate(), patient_id=patient_id)
    completed_at = _resolve_completed_at(occurred_at)
    target_date = _resolve_latest_incomplete_task_date(
        patient_id=patient_id,
        task_type=choices.PlanItemCategory.CHECKUP,
        completed_at=completed_at,
    )
    if not target_date:
        return 0

    return DailyTask.objects.filter(
        patient_id=patient_id,
        task_date=target_date,
        task_type=choices.PlanItemCategory.CHECKUP,
        status__in=[
            choices.TaskStatus.PENDING,
            choices.TaskStatus.NOT_STARTED,
        ],
    ).update(status=choices.TaskStatus.COMPLETED, completed_at=completed_at)


def _resolve_adherence_date_range(
    start_date: date | None,
    end_date: date | None,
) -> tuple[date, date]:
    """
    【功能说明】
    - 统一依从性计算的日期范围解析。

    【规则说明】
    - 默认 end_date = 昨天（本地日期）。
    - 默认 start_date = end_date 往前推 179 天（含起止共 180 天）。

    【参数说明】
    - start_date: date | None，开始日期（含）。
    - end_date: date | None，结束日期（含）。

    【返回值说明】
    - (start_date, end_date)。
    """
    if end_date is None:
        end_date = timezone.localdate() - timedelta(days=1)
    if start_date is None:
        start_date = end_date - timedelta(days=179)
    if start_date > end_date:
        raise ValueError("start_date 不能晚于 end_date")
    return start_date, end_date


def get_adherence_metrics(
    patient_id: int,
    adherence_type: int | str,
    start_date: date | None = None,
    end_date: date | None = None,
    refresh: bool = True,
) -> dict:
    """
    【功能说明】
    - 计算指定患者在时间范围内的依从性（按任务完成率统计）。
    - 依从性 = 已完成任务数 / 计划任务数。
    - 未来任务（未开始）不参与统计。

    【使用方法】
    - get_adherence_metrics(patient_id, choices.PlanItemCategory.MEDICATION)
    - get_adherence_metrics(patient_id, MetricType.BLOOD_PRESSURE, start_date, end_date)
    - get_adherence_metrics(patient_id, MONITORING_ADHERENCE_ALL, start_date, end_date)

    【适用类型】
    - choices.PlanItemCategory: MEDICATION / CHECKUP / QUESTIONNAIRE / MONITORING。
    - health_data.models.MetricType: 血压/血氧/心率/体重/体温/步数等具体监测项。
    - MONITORING_ADHERENCE_ALL: 综合监测依从率（六项监测汇总）。

    【参数说明】
    - patient_id: int，患者 ID。
    - adherence_type: int | str，依从性类型（复用现有枚举）。
    - start_date / end_date: date | None，统计区间（含起止）。

    【返回值说明】
    - dict，结构示例：
      {
        "type": adherence_type,
        "start_date": date,
        "end_date": date,
        "total": int,
        "completed": int,
        "rate": float | None,
      }
    - 若 total=0，rate 返回 None。

    【异常说明】
    - 不支持的依从性类型：抛出 ValueError。
    """
    if refresh:
        refresh_task_statuses(as_of_date=timezone.localdate(), patient_id=patient_id)

    start_date, end_date = _resolve_adherence_date_range(start_date, end_date)
    today = timezone.localdate()
    if end_date > today:
        end_date = today
        if start_date > end_date:
            return {
                "type": adherence_type,
                "start_date": start_date,
                "end_date": end_date,
                "total": 0,
                "completed": 0,
                "rate": None,
            }

    base_qs = DailyTask.objects.filter(
        patient_id=patient_id,
        task_date__range=(start_date, end_date),
    )

    if adherence_type == MONITORING_ADHERENCE_ALL:
        template_ids = list(
            MonitoringTemplate.objects.filter(code__in=MONITORING_ADHERENCE_TYPES)
            .values_list("id", flat=True)
        )
        if not template_ids:
            return {
                "type": adherence_type,
                "start_date": start_date,
                "end_date": end_date,
                "total": 0,
                "completed": 0,
                "rate": None,
            }
        task_qs = base_qs.filter(
            task_type=choices.PlanItemCategory.MONITORING,
            plan_item__template_id__in=template_ids,
        )
    elif adherence_type in choices.PlanItemCategory.values:
        task_qs = base_qs.filter(task_type=adherence_type)
    elif adherence_type in MetricType.values:
        template_ids = list(
            MonitoringTemplate.objects.filter(code=adherence_type).values_list(
                "id", flat=True
            )
        )
        if not template_ids:
            return {
                "type": adherence_type,
                "start_date": start_date,
                "end_date": end_date,
                "total": 0,
                "completed": 0,
                "rate": None,
            }
        task_qs = base_qs.filter(
            task_type=choices.PlanItemCategory.MONITORING,
            plan_item__template_id__in=template_ids,
        )
    else:
        raise ValueError("不支持的依从性类型")

    task_qs = task_qs.exclude(status=choices.TaskStatus.NOT_STARTED)
    total = task_qs.count()
    completed = task_qs.filter(status=choices.TaskStatus.COMPLETED).count()
    rate = None if total == 0 else completed / total

    return {
        "type": adherence_type,
        "start_date": start_date,
        "end_date": end_date,
        "total": total,
        "completed": completed,
        "rate": rate,
    }


def get_adherence_metrics_batch(
    patient: PatientProfile | int,
    adherence_types: Iterable[int | str],
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict]:
    """
    【功能说明】
    - 批量计算同一患者的多种依从性，按传入类型顺序返回列表。

    【参数说明】
    - patient: PatientProfile | int，患者对象或患者 ID。
    - adherence_types: Iterable[int | str]，依从性类型集合（复用现有枚举）。
    - start_date / end_date: date | None，统计区间（含起止）。

    【返回值说明】
    - List[dict]，每项结构同 get_adherence_metrics 返回值。
    """
    patient_id = patient.id if isinstance(patient, PatientProfile) else int(patient)
    refresh_task_statuses(as_of_date=timezone.localdate(), patient_id=patient_id)
    results = []
    for adherence_type in adherence_types:
        results.append(
            get_adherence_metrics(
                patient_id=patient_id,
                adherence_type=adherence_type,
                start_date=start_date,
                end_date=end_date,
                refresh=False,
            )
        )
    return results
