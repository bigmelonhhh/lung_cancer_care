"""问卷题目模型。"""

from django.db import models

from . import choices


class QuestionnaireQuestion(models.Model):
    """问卷题目。"""

    questionnaire = models.ForeignKey(
        "core.Questionnaire",
        on_delete=models.CASCADE,
        related_name="questions",
        verbose_name="所属问卷",
    )
    section = models.CharField(
        "所属章节",
        max_length=100,
        blank=True,
        help_text="问卷内的分组标题，例如'第一部分：基本信息'。",
    )
    text = models.TextField("题目内容")
    q_type = models.CharField(
        "题目类型",
        max_length=20,
        choices=choices.QuestionType.choices,
        default=choices.QuestionType.SINGLE,
    )
    seq = models.PositiveIntegerField("排序号", default=0)
    weight = models.DecimalField(
        "权重", max_digits=5, decimal_places=2, default=1.0, help_text="题目分值权重"
    )
    is_required = models.BooleanField("是否必填", default=True)

    class Meta:
        db_table = "core_questionnaire_questions"
        verbose_name = "问卷题目"
        verbose_name_plural = "问卷题目"
        ordering = ("seq",)

    def __str__(self) -> str:
        return self.text[:20]