from django.db import models

from users.models.base import TimeStampedModel


class SMSLog(TimeStampedModel):
    """Record the result of an SMS provider request for admin auditing."""

    requested_by = models.ForeignKey(
        "users.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sms_logs",
        verbose_name="请求用户",
    )
    phone = models.CharField("接收手机号", max_length=15, db_index=True)
    content = models.TextField("短信内容")
    is_success = models.BooleanField("是否发送成功", default=False, db_index=True)

    class Meta:
        db_table = "business_support_sms_logs"
        verbose_name = "短信发送记录"
        verbose_name_plural = "短信发送记录"
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.phone} - {'成功' if self.is_success else '失败'}"
