"""Order model for market application."""

import uuid
from datetime import datetime

from django.db import models

from users.models.base import TimeStampedModel
from users.models import PatientProfile
from .product import Product


class Order(TimeStampedModel):
    """交易订单。"""

    class Status(models.IntegerChoices):
        PENDING = 0, "待支付"
        PAID = 1, "已支付"
        CANCELLED = 2, "已取消"
        REFUNDED = 3, "已退款"

    order_no = models.CharField(
        "订单编号",
        max_length=32,
        unique=True,
        blank=True,
        help_text="【说明】唯一订单编号，自动生成。",
    )
    patient = models.ForeignKey(
        PatientProfile,
        on_delete=models.PROTECT,
        related_name="orders",
        verbose_name="下单患者",
        help_text="【说明】谁购买了该商品。",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="orders",
        verbose_name="购买商品",
        help_text="【说明】购买的服务包。",
    )
    amount = models.DecimalField(
        "实际支付金额",
        max_digits=10,
        decimal_places=2,
        help_text="【说明】最终支付金额；可包含优惠。",
    )
    status = models.PositiveSmallIntegerField(
        "订单状态",
        choices=Status.choices,
        default=Status.PAID,
        help_text="【说明】交易状态；默认已支付。",
    )
    paid_at = models.DateTimeField(
        "支付时间",
        null=True,
        blank=True,
        help_text="【说明】支付成功时间；默认为当前时间。",
    )

    class Meta:
        verbose_name = "订单"
        verbose_name_plural = "订单"

    def __str__(self) -> str:
        return self.order_no or f"订单#{self.pk}"

    def save(self, *args, **kwargs):
        if not self.order_no:
            today = datetime.now().strftime("%Y%m%d")
            uid = uuid.uuid4().hex[:6].upper()
            self.order_no = f"ORD{today}{uid}"
        if self.status == self.Status.PAID and not self.paid_at:
            self.paid_at = datetime.now()
        super().save(*args, **kwargs)

