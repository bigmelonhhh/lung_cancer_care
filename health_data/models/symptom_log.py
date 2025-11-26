from django.db import models


class SymptomLog(models.Model):
    """主观症状日志表。"""

    patient = models.ForeignKey(
        "users.PatientProfile",
        on_delete=models.CASCADE,
        related_name="symptom_logs",
        verbose_name="患者",
    )
    task_id = models.BigIntegerField("任务 ID", null=True, blank=True)
    symptom_type = models.CharField("症状类型", max_length=20)
    level_score = models.IntegerField("程度评分", null=True, blank=True)
    detail_json = models.JSONField("详情 JSON", blank=True, null=True)
    recorded_at = models.DateTimeField("记录时间", null=True, blank=True)

    class Meta:
        db_table = "health_symptom_logs"
        verbose_name = "主观症状"
        verbose_name_plural = "主观症状"
