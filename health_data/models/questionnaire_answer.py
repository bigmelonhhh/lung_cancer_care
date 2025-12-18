"""问卷回答明细模型。"""

from django.db import models


class QuestionnaireAnswer(models.Model):
    """问卷的具体答题明细。"""

    submission = models.ForeignKey(
        "health_data.QuestionnaireSubmission",
        on_delete=models.CASCADE,
        related_name="answers",
        verbose_name="所属提交",
    )
    question = models.ForeignKey(
        "core.QuestionnaireQuestion",
        on_delete=models.CASCADE,
        verbose_name="题目",
    )
    # 对于单选/多选，关联具体的选项
    # 如果是多选题，同一个 question 会有多条记录
    option = models.ForeignKey(
        "core.QuestionnaireOption",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="选中选项",
    )
    # 对于填空题，或者选项的补充说明
    value_text = models.TextField("文本回答", blank=True, null=True)

    class Meta:
        db_table = "health_questionnaire_answers"
        verbose_name = "问卷回答明细"
        verbose_name_plural = "问卷回答明细"

    def __str__(self) -> str:
        return f"Answer to {self.question_id}"