from django.db import models

from users.models.base import TimeStampedModel


class DeviceMetricReceipt(TimeStampedModel):
    """Persist a provider event key so callback retries remain idempotent."""

    device = models.ForeignKey(
        "business_support.Device",
        on_delete=models.PROTECT,
        related_name="metric_receipts",
        verbose_name="设备",
    )
    provider_code = models.CharField(
        "厂商编码",
        max_length=32,
    )
    external_event_id = models.CharField(
        "外部事件标识",
        max_length=96,
    )
    metric_type = models.CharField(
        "指标类型",
        max_length=32,
    )

    class Meta:
        verbose_name = "设备指标接收记录"
        verbose_name_plural = "设备指标接收记录"
        constraints = [
            models.UniqueConstraint(
                fields=(
                    "device",
                    "provider_code",
                    "external_event_id",
                    "metric_type",
                ),
                name="uniq_device_metric_external_event",
            ),
        ]

    def __str__(self):
        return (
            f"{self.provider_code}:{self.device_id}:"
            f"{self.external_event_id}:{self.metric_type}"
        )
