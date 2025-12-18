"""题目选项模型。"""

from django.db import models


class QuestionnaireOption(models.Model):
    """题目选项。"""

    question = models.ForeignKey(
        "core.QuestionnaireQuestion",
        on_delete=models.CASCADE,
        related_name="options",
        verbose_name="所属题目",
    )
    text = models.CharField("选项内容", max_length=200)
    value = models.CharField(
        "选项值", max_length=50, blank=True, help_text="用于代码逻辑的标识值"
    )
    score = models.DecimalField(
        "分值", max_digits=8, decimal_places=2, default=0, help_text="该选项对应的得分"
    )
    seq = models.PositiveIntegerField("排序号", default=0)

    class Meta:
        db_table = "core_questionnaire_options"
        verbose_name = "题目选项"
        verbose_name_plural = "题目选项"
        ordering = ("seq",)

    def __str__(self) -> str:
        return f"{self.text} ({self.score}分)"