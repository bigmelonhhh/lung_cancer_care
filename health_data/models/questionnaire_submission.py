"""问卷提交记录模型。"""

from django.db import models


class QuestionnaireSubmission(models.Model):
    """用户的一次问卷提交记录。"""

    patient = models.ForeignKey(
        "users.PatientProfile",
        on_delete=models.CASCADE,
        related_name="questionnaire_submissions",
        verbose_name="患者",
    )
    questionnaire = models.ForeignKey(
        "core.Questionnaire",
        on_delete=models.CASCADE,
        related_name="submissions",
        verbose_name="问卷模板",
    )
    task_id = models.BigIntegerField("关联任务ID", null=True, blank=True)

    # 冗余存储计算后的总分，方便查询
    total_score = models.DecimalField(
        "总分", max_digits=10, decimal_places=2, null=True, blank=True
    )

    created_at = models.DateTimeField("提交时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "health_questionnaire_submissions"
        verbose_name = "问卷提交记录"
        verbose_name_plural = "问卷提交记录"
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.patient_id} - {self.questionnaire_id}"