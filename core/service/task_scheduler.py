"""治疗计划任务调度服务。

本模块负责根据治疗疗程与计划条目，
在指定日期生成对应的 `DailyTask` 记录。

【设计约定】
- 仅按“某一天”生成任务，不一次性生成整个周期；
- 计划条目 `schedule_days` 使用 1 基天数：
  1 表示 `TreatmentCycle.start_date` 当天，N 表示第 N 天；
- 已生成的历史 `DailyTask` 不会被计划的后续修改回写；
- 对同一天、同一条计划多次调用应保持幂等，不重复生成任务。
"""

from __future__ import annotations

from datetime import date

from django.db import models, transaction

from core.models import choices, DailyTask, PlanItem, TreatmentCycle


@transaction.atomic
def generate_daily_tasks_for_date(task_date: date) -> int:
    """为指定日期生成每日任务。

    【业务说明】
    - 基于治疗疗程与计划条目生成“治疗计划任务”（包含用药/复查/问卷/监测等类别）；
    - 所有任务最终统一落地到 `DailyTask`，调用入口保持单一。

    Args:
        task_date: 需要生成任务的日期。

    Returns:
        实际新生成的 `DailyTask` 数量（计划任务 + 监测任务）。
    """

    created_count = 0
    created_count += _generate_plan_item_tasks_for_date(task_date)
    return created_count


def _generate_plan_item_tasks_for_date(task_date: date) -> int:
    """生成基于 PlanItem 的治疗计划任务。"""

    # 1. 选出在 task_date 当天有效的疗程
    cycles = (
        TreatmentCycle.objects.filter(start_date__lte=task_date)
        .exclude(
            status__in=[
                choices.TreatmentCycleStatus.COMPLETED,
                choices.TreatmentCycleStatus.TERMINATED,
            ]
        )
        .filter(
            models.Q(end_date__isnull=True) | models.Q(end_date__gte=task_date),
        )
        .prefetch_related("plan_items")
    )

    created_count = 0

    for cycle in cycles:
        # 以 1 为基数的周期天数
        day_index = (task_date - cycle.start_date).days + 1
        if day_index <= 0:
            # 理论上已由 start_date__lte 过滤，此处为安全检查
            continue

        # 仅处理处于激活状态的计划条目
        plan_items = [
            item
            for item in cycle.plan_items.all()
            if item.status == choices.PlanItemStatus.ACTIVE
        ]

        for item in plan_items:
            # 未配置调度天数或当前天不在调度列表中，跳过
            if not item.schedule_days or day_index not in item.schedule_days:
                continue

            # 幂等性保证：如果已存在同一患者、同一计划、同一天的任务，则不重复创建
            _, created = DailyTask.objects.get_or_create(
                patient=cycle.patient,
                plan_item=item,
                task_date=task_date,
                defaults=_build_task_defaults_from_plan_item(item),
            )
            if created:
                created_count += 1

    return created_count


def _build_task_defaults_from_plan_item(plan_item: PlanItem) -> dict:
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

    # 检查任务可以在后续根据 checkup 模板补充关联报告类型等信息
    related_report_type = None
    if plan_item.category == choices.PlanItemCategory.CHECKUP and plan_item.checkup:
        # 这里预留从检查库模板中继承报告类型的能力
        related_report_type = getattr(plan_item.checkup, "report_type", None)

    return {
        "task_type": plan_item.category,
        "title": title,
        "detail": detail,
        "status": choices.TaskStatus.PENDING,
        "related_report_type": related_report_type,
        # 快照当前交互配置，后续不随 PlanItem 变化
        "interaction_payload": plan_item.interaction_config or {},
    }
