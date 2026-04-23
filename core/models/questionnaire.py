"""问卷模板定义。"""

from django.db import models


class QuestionnaireCode(models.TextChoices):
    Q_PHYSICAL = "Q_PHYSICAL", "体能评分"
    Q_BREATH = "Q_BREATH", "呼吸困难评估"
    Q_COUGH = "Q_COUGH", "咳嗽与痰色评估"
    Q_APPETITE = "Q_APPETITE", "食欲评估"
    Q_PAIN = "Q_PAIN", "身体疼痛评估"
    Q_SLEEP = "Q_SLEEP", "睡眠质量评估"
    Q_DEPRESSIVE = "Q_DEPRESSIVE", "抑郁评估"
    Q_ANXIETY = "Q_ANXIETY", "焦虑评估"
    Q_KQNMLB = "Q_KQNMLB", "口腔黏膜损伤自评量表"
    Q_PSYCH = "Q_PSYCH", "心理痛苦分级评估"


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
