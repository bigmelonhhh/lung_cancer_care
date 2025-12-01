from django.db import models
from users.models.base import TimeStampedModel  # 复用你的基础时间戳模型

class Device(TimeStampedModel):
    """
    【业务说明】智能设备资产库 (放在 Core 应用作为通用资源)。
    【核心职责】维护硬件设备的物理信息、固件版本及当前的归属状态。
    """

    # --- 枚举定义 ---
    class DeviceType(models.IntegerChoices):
        WATCH = 1, "智能手表"
        

    # --- 1. 物理身份 (扫描/入库信息) ---
    sn = models.CharField(
        "设备SN码",
        max_length=64,
        unique=True,
        db_index=True,  # 核心查询字段，显式加索引
        help_text="【业务说明】设备唯一物理标识；【来源】扫描字段 sn；【示例】ZK204X..."
    )
    
    imei = models.CharField(
        "IMEI",
        max_length=64,
        unique=True,
        blank=True,
        help_text="【业务说明】蜂窝网络标识，如有则必须唯一；【来源】扫描字段 imei"
    )

    # --- 2. 设备属性 (元数据) ---
    model_name = models.CharField(
        "硬件型号",
        max_length=64,
        blank=True,
        help_text="【来源】扫描字段 model，如 ZK204"
    )
    
    ble_name = models.CharField(
        "蓝牙广播名",
        max_length=64,
        blank=True,
        help_text="【来源】扫描字段 ble，用于蓝牙连接匹配"
    )
    
    firmware_version = models.CharField(
        "固件版本",
        max_length=64,
        blank=True,
        help_text="【来源】扫描字段 version，用于判断是否需要 OTA 升级"
    )

    device_type = models.PositiveSmallIntegerField(
        "设备类型",
        choices=DeviceType.choices,
        default=DeviceType.WATCH,
        help_text="【业务说明】设备分类枚举"
    )

    is_active = models.BooleanField(
        "是否有效",
        default=True,
        db_index=True,  # <--- 建议加上这个
        help_text="【业务说明】软删除标记；【用法】设备报废或误录入删除时置为False，不物理删除以保留历史数据"
    )

    # --- 3. 动态业务状态 (流转信息) ---
    # 这里关联 users 应用，属于跨 App 外键，使用字符串引用避免循环导入
    current_patient = models.ForeignKey(
        "users.PatientProfile",
        on_delete=models.SET_NULL,  # 设备解绑后，设备记录保留，只是归属为空
        null=True,
        blank=True,
        related_name="devices",
        verbose_name="当前绑定患者",
        help_text="【业务说明】当前设备在谁手上；【用法】库存状态时为 NULL"
    )

    bind_at = models.DateTimeField(
        "最近绑定时间",
        null=True,
        blank=True,
        help_text="【业务说明】发放给当前患者的时间，每次绑定更新"
    )

    last_active_at = models.DateTimeField(
        "最后活跃时间",
        null=True,
        blank=True,
        help_text="【业务说明】最后一次上报数据或心跳的时间，用于判断设备是否离线"
    )

    class Meta:
        verbose_name = "智能设备"
        verbose_name_plural = "设备库"
        indexes = [
            # 联合索引优化：常用于查询“某类设备的在线情况”
            models.Index(fields=['device_type', 'last_active_at']),
        ]

    def __str__(self):
        # 在 Admin 或日志中显示：[手表] ZK204X...(张三)
        patient_str = f"-{self.current_patient.name}" if self.current_patient else "[库存]"
        return f"[{self.get_device_type_display()}] {self.sn} {patient_str}"

    def save(self, *args, **kwargs):
        # 数据清洗：入库时自动去除首尾空格，防止 copy-paste 错误
        if self.sn:
            self.sn = self.sn.strip()
        if self.imei:
            self.imei = self.imei.strip()
        super().save(*args, **kwargs)