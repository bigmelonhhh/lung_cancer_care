"""问卷模板定义。"""

from django.db import models


class Questionnaire(models.Model):
    """问卷模板（原随访计划模板）。"""

    name = models.CharField("问卷名称", max_length=50)
    code = models.CharField(
        "问卷编码",
        max_length=50,
        unique=True,
        help_text="唯一英文编码，例如 Q_PAIN、Q_SLEEP。",
    )
    calculation_strategy = models.CharField(
        "计分策略",
        max_length=50,
        default="SUM",
        help_text="SUM: 简单累加; AVG: 平均分; CUSTOM_*: 特殊算法",
    )
    schedule_days_template = models.JSONField(
        "推荐执行天(周期内)",
        default=list,
        blank=True,
        help_text="周期内执行的 DayIndex 集合，例如 [7, 14, 21]。",
    )
    is_active = models.BooleanField("是否启用", default=True)
    sort_order = models.PositiveIntegerField("排序权重", default=0)

    class Meta:
        db_table = "core_questionnaires"
        verbose_name = "问卷模板"
        verbose_name_plural = "问卷模板"
        ordering = ("sort_order", "name")

    def __str__(self) -> str:
        return self.name
