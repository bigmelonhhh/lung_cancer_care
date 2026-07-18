from django.db import models

from users.models.base import TimeStampedModel


class DeviceProvider(TimeStampedModel):
    """
    Device data provider/vendor managed by the platform.

    The provider code is the stable integration key used by callback routing and
    adapter lookup. It is normalized to uppercase to keep admin-created records
    compatible with URL and service-level lookups.
    """

    code = models.CharField(
        "厂商编码",
        max_length=32,
        unique=True,
        db_index=True,
        help_text="系统内稳定编码，例如 HRT。",
    )
    name = models.CharField(
        "厂商名称",
        max_length=64,
        help_text="后台展示名称，例如 HRT。",
    )
    is_active = models.BooleanField(
        "是否启用",
        default=True,
        db_index=True,
        help_text="停用后不再接收该厂商新上报数据。",
    )
    description = models.TextField(
        "说明",
        blank=True,
        help_text="厂商接口、联系人或运维说明。",
    )

    class Meta:
        verbose_name = "设备厂商"
        verbose_name_plural = "设备厂商"
        ordering = ("code",)

    def __str__(self):
        return f"{self.code} - {self.name}"

    def save(self, *args, **kwargs):
        if self.code:
            self.code = self.code.strip().upper()
        if self.name:
            self.name = self.name.strip()
        super().save(*args, **kwargs)
