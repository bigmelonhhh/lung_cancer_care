from django.db import models


class MetricType(models.TextChoices):
    BLOOD_PRESSURE = "M_BP", "血压"
    BLOOD_OXYGEN = "M_SPO2", "血氧"
    HEART_RATE = "M_HR", "心率"
    STEPS = "M_STEPS", "步数"
    WEIGHT = "M_WEIGHT", "体重"
    BODY_TEMPERATURE = "M_TEMP", "体温"
    USE_MEDICATED = "M_USE_MEDICATED", "用药情况"

   


class MetricSource(models.TextChoices):
    DEVICE = "device", "设备"
    MANUAL = "manual", "手动"


class ActiveHealthMetricManager(models.Manager):
    """
    默认只返回 is_active=True 的健康指标记录。

    - 业务读取场景（Service / View）通常通过 HealthMetric.objects 访问，
      因此天然只会看到“有效记录”，被软删除的数据会自动排除。
    - 如需查询包含软删除在内的所有记录，可以显式使用 HealthMetric.all_objects。
    """

    def get_queryset(self):
        return super().get_queryset().filter(is_active=True)


class HealthMetric(models.Model):
    """体征指标记录表。"""

    patient = models.ForeignKey(
        "users.PatientProfile",
        on_delete=models.CASCADE,
        related_name="health_metrics",
        verbose_name="患者",
    )
    task_id = models.BigIntegerField("任务 ID", null=True, blank=True)
    metric_type = models.CharField(
        "指标类型", max_length=50, choices=MetricType.choices
    )
    source = models.CharField(
        "数据来源", max_length=20, choices=MetricSource.choices, default=MetricSource.DEVICE
    )
    value_main = models.DecimalField("主数值", max_digits=10, decimal_places=2, null=True, blank=True)
    value_sub = models.DecimalField(
        "副数值", max_digits=10, decimal_places=2, null=True, blank=True
    )
    questionnaire_submission = models.ForeignKey(
        "health_data.QuestionnaireSubmission",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="derived_metrics",
        verbose_name="来源问卷提交",
    )
    measured_at = models.DateTimeField("测量时间")
    is_active = models.BooleanField("是否有效", default=True, db_index=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    

    # 默认 Manager：只返回 is_active=True 的记录
    objects = ActiveHealthMetricManager()
    # all_objects：返回所有记录（包括已软删除）
    all_objects = models.Manager()

    class Meta:
        db_table = "health_metrics"
        verbose_name = "客观指标"
        verbose_name_plural = "客观指标"

    @property
    def display_value(self) -> str:
        """
        友好展示用的指标值字符串。

        【设计目的】
        - 将「某条体征记录如何展示给用户」的逻辑收敛在模型自身，
          避免在 Service / View 中到处拼文案。
        - 对同一个 HealthMetric 实例，在模板、Serializer、管理后台等
          所有地方都可以统一使用 `metric.display_value` 获取展示文案。

        【返回规则（示例）】
        - 数值型指标：
          - 血压 (blood_pressure)： "收缩压/舒张压"，如 "120/80"
          - 体重 (weight)：         "XX kg"，如 "68.3 kg"
          - 体温 (body_temperature)："XX °C"，如 "36.5 °C"
          - 血氧 (blood_oxygen)：   "XX%"，如 "98%"
          - 心率 (heart_rate)：     "XX bpm"，如 "80 bpm"
          - 步数 (steps)：          "XXXX 步"，如 "12345 步"
        - 其他未特殊处理的指标：直接返回主值的字符串形式 `str(value_main)`。

        【使用示例】
        >>> metric = HealthMetric.objects.get(id=1)
        >>> metric.metric_type
        'blood_pressure'
        >>> metric.value_main, metric.value_sub
        (Decimal('120.00'), Decimal('80.00'))
        >>> metric.display_value
        '120/80'
        """
        val_main = self.value_main
        val_sub = self.value_sub
        m_type = self.metric_type

        if val_main is None:
            return ""

        # 1. 处理特定格式的数值指标
        if m_type == MetricType.BLOOD_PRESSURE:
            sbp = int(val_main)
            dbp = int(val_sub) if val_sub is not None else "?"
            return f"{sbp}/{dbp}"

        if m_type == MetricType.WEIGHT:
            return f"{float(val_main):g} kg"

        if m_type == MetricType.BODY_TEMPERATURE:
            return f"{float(val_main):g} °C"

        if m_type == MetricType.BLOOD_OXYGEN:
            return f"{int(val_main)}%"

        if m_type == MetricType.HEART_RATE:
            return f"{int(val_main)} bpm"

        if m_type == MetricType.STEPS:
            return f"{int(val_main)} 步"

        # 2. 默认情况
        return str(val_main)
