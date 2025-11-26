from django.db import models


class HealthMetric(models.Model):
    """体征指标记录表。"""

    patient = models.ForeignKey(
        "users.PatientProfile",
        on_delete=models.CASCADE,
        related_name="health_metrics",
        verbose_name="患者",
    )
    task_id = models.BigIntegerField("任务 ID", null=True, blank=True)
    metric_type = models.CharField("指标类型", max_length=20)
    value_main = models.DecimalField("主数值", max_digits=10, decimal_places=2)
    value_sub = models.DecimalField(
        "副数值", max_digits=10, decimal_places=2, null=True, blank=True
    )
    measured_at = models.DateTimeField("测量时间")

    class Meta:
        db_table = "health_metrics"
        verbose_name = "客观指标"
        verbose_name_plural = "客观指标"
