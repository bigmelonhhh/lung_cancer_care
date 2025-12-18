"""日常监测相关模型。"""

from django.db import models


class MonitoringTemplate(models.Model):
    """
    一般监测模板定义（类似 Questionnaire）：
    - 表示“体温/血氧/体重/血压/心率/步数”等标准监测项目；
    - 仅包含模板属性本身，不绑定具体患者。
    """

    name = models.CharField("监测名称", max_length=50)
    code = models.CharField(
        "监测编码",
        max_length=50,
        unique=True,
        help_text="唯一英文编码，例如 M_TEMP、M_SPO2。",
    )
    metric_type = models.CharField(
        "关联指标类型",
        max_length=50,
        blank=True,
        null=True,
        help_text="对应 HealthMetric.MetricType，用于将监测结果映射到指标表。",
    )
    schedule_days_template = models.JSONField(
        "推荐执行天(周期内)",
        default=list,
        blank=True,
        help_text="周期内执行的 DayIndex 集合，例如 [1,3,5,7] 表示每2天一次。",
    )
    is_active = models.BooleanField("是否启用", default=True)
    sort_order = models.PositiveIntegerField("排序权重", default=0)

    class Meta:
        db_table = "core_monitoring_templates"
        verbose_name = "监测模板"
        verbose_name_plural = "监测模板"
        ordering = ("sort_order", "name")

    def __str__(self) -> str:
        return self.name
