from django.db import models


class MetricType(models.TextChoices):
    BLOOD_PRESSURE = "blood_pressure", "血压"
    BLOOD_OXYGEN = "blood_oxygen", "血氧"
    HEART_RATE = "heart_rate", "心率"
    STEPS = "steps", "步数"
    WEIGHT = "weight", "体重"
    BODY_TEMPERATURE = "body_temperature", "体温"
    PHYSICAL_PERFORMANCE = "physical_performance", "体能评分 (ECOG)"
    SLEEP_QUALITY = "sleep_quality", "睡眠质量"
    APPETITE = "appetite", "食欲评分"
    PSYCHOLOGICAL_DISTRESS = "psychological_distress", "心理痛苦评分"
    SPUTUM_COLOR = "sputum_color", "痰色"
    COUGH = "cough", "咳嗽"
    DYSPNEA = "dyspnea", "呼吸困难 (mMRC)"
    PAIN_INCISION = "pain_incision", "疼痛-胸口术口"
    PAIN_SHOULDER = "pain_shoulder", "疼痛-肩部"
    PAIN_BONE = "pain_bone", "疼痛-骨头"
    PAIN_HEAD = "pain_head", "疼痛-头"


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
    measured_at = models.DateTimeField("测量时间")
    is_active = models.BooleanField("是否有效", default=True, db_index=True)

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
        - 评分/枚举型指标（如痰色、疼痛等级、ECOG 体能状态）：
          使用 `METRIC_SCALES` 中配置的说明文本，例如：
            - 体能评分 2 -> "生活自理，但不能工作（日间卧床时间 < 50%）"
            - 痰色 3     -> "黄绿色/脓性（提示细菌感染，需警惕）"
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

        # 1. 优先处理枚举/评分映射 (如痰色、疼痛、ECOG)
        if m_type in METRIC_SCALES:
            try:
                int_val = int(val_main)
                return METRIC_SCALES[m_type].get(int_val, str(int_val))
            except (ValueError, TypeError):
                return str(val_main)

        # 2. 处理特定格式的数值指标
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

        # 3. 默认情况
        return str(val_main)


# 指标分值描述映射配置
METRIC_SCALES = {
    MetricType.PHYSICAL_PERFORMANCE: {
        0: "活动自如（无症状，能进行所有病前活动）",
        1: "轻度受限（不能从事剧烈活动，但能行走，能从事轻体力工作）",
        2: "生活自理，但不能工作（日间卧床时间 < 50%）",
        3: "生活仅部分自理（日间卧床时间 > 50%）",
        4: "完全卧床（不能自理，完全卧床）",
    },
    MetricType.SLEEP_QUALITY: {
        1: "非常差（彻夜难眠，严重影响白天精神）",
        2: "差（入睡困难或频繁醒来，睡眠不足）",
        3: "一般（能睡着，但感觉不够深或时间不够）",
        4: "良好（睡眠基本正常，醒后精神尚可）",
        5: "非常好（一觉睡到天亮，精力充沛）",
    },
    MetricType.APPETITE: {
        0: "完全无食欲",
        1: "食欲极差",
        2: "食欲很差",
        3: "食欲差",
        4: "食欲稍差",
        5: "食欲一般",
        6: "食欲尚可",
        7: "食欲良好",
        8: "食欲很好",
        9: "食欲极好",
        10: "食欲正常（与病前无异）",
    },
    MetricType.PSYCHOLOGICAL_DISTRESS: {
        0: "无痛苦（心情平静/愉快）",
        1: "轻微痛苦",
        2: "轻度痛苦",
        3: "中度痛苦",
        4: "比较痛苦",
        5: "痛苦明显",
        6: "严重痛苦",
        7: "非常痛苦",
        8: "剧烈痛苦",
        9: "极度痛苦",
        10: "无法忍受的痛苦",
    },
    MetricType.SPUTUM_COLOR: {
        0: "无痰",
        1: "白色/透明（正常，泡沫样或粘液样）",
        2: "黄色（可能存在轻度感染）",
        3: "黄绿色/脓性（提示细菌感染，需警惕）",
        4: "铁锈色/暗红色（陈旧性出血）",
        5: "鲜红色/血痰（活动性出血，需立即就医）",
    },
    MetricType.COUGH: {
        0: "无咳嗽",
        1: "轻度（间断咳嗽，不影响生活）",
        2: "中度（频繁咳嗽，轻度影响睡眠或说话）",
        3: "重度（持续剧烈咳嗽，严重影响睡眠，伴胸痛）",
    },
    MetricType.DYSPNEA: {
        0: "剧烈运动时才感觉呼吸困难",
        1: "平地快走或爬缓坡时感觉呼吸困难",
        2: "因为呼吸困难，平地行走比同龄人慢，或需要停下来休息",
        3: "平地行走100米或数分钟后需要停下来喘气",
        4: "严重的呼吸困难，不能离开家或穿脱衣服时也感到气短",
    },
    # 疼痛通用量表 (NRS 0-10)
    MetricType.PAIN_INCISION: {i: f"{i}分" for i in range(11)},
    MetricType.PAIN_SHOULDER: {i: f"{i}分" for i in range(11)},
    MetricType.PAIN_BONE: {i: f"{i}分" for i in range(11)},
    MetricType.PAIN_HEAD: {i: f"{i}分" for i in range(11)},
}
