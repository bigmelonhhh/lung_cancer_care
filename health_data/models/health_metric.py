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

    class Meta:
        db_table = "health_metrics"
        verbose_name = "客观指标"
        verbose_name_plural = "客观指标"


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
