from django.db import models

from . import choices
from .treatment_cycle import TreatmentCycle


class PlanItem(models.Model):
    """疗程下的具体执行条目。"""

    cycle = models.ForeignKey(
        TreatmentCycle,
        on_delete=models.CASCADE,
        related_name="plan_items",
        verbose_name="所属疗程",
    )

    
    category = models.PositiveSmallIntegerField("类型", choices=choices.PlanItemCategory.choices)
    medicine = models.ForeignKey(
        "core.Medication",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="plan_items",
        verbose_name="药品模板",
    )
    checkup = models.ForeignKey(
        "core.CheckupLibrary",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="plan_items",
        verbose_name="复查模板",
    )
    questionnaire = models.ForeignKey(
        "core.Questionnaire",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="plan_items",
        verbose_name="问卷模板",
    )
    item_name = models.CharField("项目名称", max_length=100)
    drug_dosage = models.CharField("单次用量", max_length=50, blank=True)
    drug_usage = models.CharField("用法", max_length=50, blank=True)
    schedule_days = models.JSONField(
        "调度天数",
        default=list,
        blank=True,
        help_text="当 schedule_type=CUSTOM 时使用，例如 [1,8,15]。",
    )
    status = models.PositiveSmallIntegerField(
        "状态",
        choices=choices.PlanItemStatus.choices,
        default=choices.PlanItemStatus.ACTIVE,
    )
    priority_level = models.CharField(
        "治疗阶段",
        max_length=20,
        choices=choices.PriorityLevel.choices,
        blank=True,
    )
    interaction_config = models.JSONField(
        "交互配置",
        blank=True,
        default=dict,
        help_text='随访问卷/复查注意事项配置，例如 {"modules":["pain"]}',
    )

    class Meta:
        db_table = "core_plan_items"
        verbose_name = "疗程计划条目"
        verbose_name_plural = "疗程计划条目"
        indexes = [
            models.Index(fields=["cycle", "category"], name="idx_cycle_category"),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.item_name} ({self.get_category_display()})"
