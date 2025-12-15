"""Product model for market application."""

from django.db import models

from users.models.base import TimeStampedModel


class Product(TimeStampedModel):
    """商品/服务包。"""

    name = models.CharField(
        "商品名称",
        max_length=100,
        help_text="【说明】服务包名称；【示例】VIP 监护服务",
    )
    price = models.DecimalField(
        "销售价格",
        max_digits=10,
        decimal_places=2,
        help_text="【说明】标注售价；【示例】199.00",
    )
    service_content = models.TextField(
        "服务包内容",
        blank=True,
        help_text="【说明】服务包具体内容及权益说明；可填写几百字的描述。",
    )
    duration_days = models.PositiveIntegerField(
        "服务有效期（天）",
        help_text="【说明】服务有效天数；【示例】30",
    )
    is_active = models.BooleanField(
        "是否上架",
        default=True,
        help_text="【说明】控制商品销售状态；1=上架，0=下架",
    )

    class Meta:
        verbose_name = "商品/服务包"
        verbose_name_plural = "商品/服务包"

    def __str__(self) -> str:
        return f"{self.name} - ¥{self.price}"

