"""日常监测配置相关模型。"""

from datetime import time

from django.db import models


class MonitoringConfig(models.Model):
    """患者监测任务配置，控制每日生成哪些监测任务。"""

    patient = models.OneToOneField(
        "users.PatientProfile",
        primary_key=True,
        on_delete=models.CASCADE,
        related_name="monitoring_config",
        verbose_name="患者",
        help_text="绑定的患者档案；删除患者时自动清理配置。",
    )
    check_freq_days = models.PositiveIntegerField(
        "监测频率(天)",
        default=1,
        help_text="监测任务的生成间隔天数，默认每日一次。",
    )
    enable_temp = models.BooleanField("启用体温监测", default=False)
    last_gen_date_temp = models.DateField("体温上次生成日期", null=True, blank=True)
    enable_spo2 = models.BooleanField("启用血氧监测", default=True)
    last_gen_date_spo2 = models.DateField("血氧上次生成日期", null=True, blank=True)
    enable_weight = models.BooleanField("启用体重监测", default=False)
    last_gen_date_weight = models.DateField("体重上次生成日期", null=True, blank=True)
    enable_bp = models.BooleanField("启用血压监测", default=False)
    last_gen_date_bp = models.DateField("血压上次生成日期", null=True, blank=True)
    enable_step = models.BooleanField("启用步数监测", default=False)
    last_gen_date_step = models.DateField("步数上次生成日期", null=True, blank=True)
    daily_check_time = models.TimeField(
        "每日生成时间",
        default=time(9, 0, 0),
        help_text="每天调度监测任务的时间。",
    )

    class Meta:
        db_table = "core_monitoring_configs"
        verbose_name = "监测配置"
        verbose_name_plural = "监测配置"

    def __str__(self) -> str:  # pragma: no cover - 仅用于后台展示
        return f"{self.patient.name} 的监测配置"
