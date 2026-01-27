"""治疗计划任务调度服务。

本模块负责根据治疗疗程与计划条目，
在指定日期生成对应的 `DailyTask` 记录。

【设计约定】
- 可按指定日期生成“从该日期起”的未来任务；
- 计划条目 `schedule_days` 使用 1 基天数：
  1 表示 `TreatmentCycle.start_date` 当天，N 表示第 N 天；
- 已生成的历史 `DailyTask` 不会被计划的后续修改回写；
- 对同一天、同一条计划多次调用应保持幂等，不重复生成任务。
"""

from __future__ import annotations

from datetime import date, timedelta

from django.db import models, transaction

from core.models import CheckupLibrary, choices, DailyTask, PlanItem, TreatmentCycle
from core.service.tasks import resolve_task_status


@transaction.atomic
def generate_daily_tasks_for_date(task_date: date = date.today()) -> int:
    """为指定日期生成每日任务（含未来任务）。

    【业务说明】
    - 基于治疗疗程与计划条目生成“治疗计划任务”（包含用药/复查/问卷/监测等类别）；
    - 所有任务最终统一落地到 `DailyTask`，调用入口保持单一。

    Args:
        task_date: 任务生成起始日期。

    Returns:
        实际新生成的 `DailyTask` 数量（计划任务）。
    """

    created_count = 0
    _cleanup_plan_item_tasks_for_date(task_date)
    created_count += _generate_plan_item_tasks_for_date(task_date)
    return created_count


def _cleanup_plan_item_tasks_for_date(task_date: date) -> None:
    """清理已失效的计划任务（仅删除未完成任务）。"""

    removable_statuses = [
        choices.TaskStatus.PENDING,
        choices.TaskStatus.NOT_STARTED,
        choices.TaskStatus.TERMINATED,
    ]

    # 已删除计划项（plan_item 为空）的未来任务直接清理
    DailyTask.objects.filter(
        plan_item__isnull=True,
        task_date__gte=task_date,
        status__in=removable_statuses,
    ).delete()

    # 停用计划项的未来任务清理
    disabled_plan_item_ids = list(
        PlanItem.objects.filter(status=choices.PlanItemStatus.DISABLED).values_list("id", flat=True)
    )
    if disabled_plan_item_ids:
        DailyTask.objects.filter(
            plan_item_id__in=disabled_plan_item_ids,
            task_date__gte=task_date,
            status__in=removable_statuses,
        ).delete()

    # 终止疗程：清理未开始任务
    terminated_cycle_ids = list(
        TreatmentCycle.objects.filter(
            status=choices.TreatmentCycleStatus.TERMINATED
        ).values_list("id", flat=True)
    )
    if terminated_cycle_ids:
        DailyTask.objects.filter(
            plan_item__cycle_id__in=terminated_cycle_ids,
            status=choices.TaskStatus.NOT_STARTED,
        ).delete()

    # 清理调度日被移除的任务（仅针对进行中疗程）
    active_plan_items = (
        PlanItem.objects.filter(
            status=choices.PlanItemStatus.ACTIVE,
            cycle__status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        .select_related("cycle")
    )
    for item in active_plan_items:
        cycle = item.cycle
        cycle_end = cycle.end_date or (
            cycle.start_date + timedelta(days=cycle.cycle_days - 1)
        )

        valid_dates = set()
        for day_index in item.schedule_days or []:
            if day_index <= 0:
                continue
            task_date_for_item = cycle.start_date + timedelta(days=day_index - 1)
            if task_date_for_item < task_date or task_date_for_item > cycle_end:
                continue
            valid_dates.add(task_date_for_item)

        tasks = DailyTask.objects.filter(
            plan_item=item,
            task_date__gte=task_date,
            status__in=removable_statuses,
        )
        if valid_dates:
            tasks = tasks.exclude(task_date__in=valid_dates)
        tasks.delete()


def _generate_plan_item_tasks_for_date(task_date: date) -> int:
    """生成基于 PlanItem 的治疗计划任务（从 task_date 起的未来任务）。"""

    cycles = (
        TreatmentCycle.objects.exclude(
            status__in=[
                choices.TreatmentCycleStatus.COMPLETED,
                choices.TreatmentCycleStatus.TERMINATED,
            ]
        )
        .filter(models.Q(end_date__isnull=True) | models.Q(end_date__gte=task_date))
        .prefetch_related("plan_items")
    )

    created_count = 0

    for cycle in cycles:
        cycle_end = cycle.end_date or (
            cycle.start_date + timedelta(days=cycle.cycle_days - 1)
        )
        if cycle_end < task_date:
            continue

        start_date = max(task_date, cycle.start_date)

        plan_items = [
            item
            for item in cycle.plan_items.all()
            if item.status == choices.PlanItemStatus.ACTIVE
        ]

        for item in plan_items:
            if not item.schedule_days:
                continue

            for day_index in item.schedule_days:
                if day_index <= 0:
                    continue
                task_date_for_item = cycle.start_date + timedelta(days=day_index - 1)
                if task_date_for_item < start_date or task_date_for_item > cycle_end:
                    continue

                status = resolve_task_status(
                    task_type=item.category,
                    task_date=task_date_for_item,
                    as_of_date=task_date,
                )
                _, created = DailyTask.objects.get_or_create(
                    patient=cycle.patient,
                    plan_item=item,
                    task_date=task_date_for_item,
                    defaults=_build_task_defaults_from_plan_item(item, status=status),
                )
                if created:
                    created_count += 1

    return created_count


def _build_task_defaults_from_plan_item(plan_item: PlanItem, *, status: int) -> dict:
    """根据计划条目构造生成 `DailyTask` 时使用的默认字段。

    【注意】
    - 仅用于新建任务时的初始快照；
    - 后续修改 `PlanItem` 不会回写历史任务。
    """

    title = plan_item.item_name

    # 文本描述可按类型做简单区分，后续可按需扩展
    detail_parts = []
    if plan_item.category == choices.PlanItemCategory.MEDICATION:
        if plan_item.drug_dosage:
            detail_parts.append(f"单次用量：{plan_item.drug_dosage}")
        if plan_item.drug_usage:
            detail_parts.append(f"用法：{plan_item.drug_usage}")

    detail = "\n".join(detail_parts) if detail_parts else ""

    # 检查任务从检查库模板继承关联报告类型
    related_report_type = None
    if plan_item.category == choices.PlanItemCategory.CHECKUP:
        template = CheckupLibrary.objects.filter(pk=plan_item.template_id).first()
        if template:
            related_report_type = template.related_report_type

    return {
        "task_type": plan_item.category,
        "title": title,
        "detail": detail,
        "status": status,
        "related_report_type": related_report_type,
        # 快照当前交互配置，后续不随 PlanItem 变化
        "interaction_payload": {},
    }
