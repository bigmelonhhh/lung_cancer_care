from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError

if TYPE_CHECKING:
    from users.models import SalesProfile

class SalesService:
    """销售端相关服务。"""

    @classmethod
    def generate_permanent_qrcode(cls, sales_id: int) -> str:
        """
        为销售生成永久二维码，便于线索扫码绑定。
        场景值：bind_sales_{sales_id}
        """

        if not sales_id:
            raise ValidationError("缺少销售 ID")

        scene_str = f"bind_sales_{sales_id}"
        try:
            from wx.services.client import wechat_client
            res = wechat_client.qrcode.create(
                {
                    "action_name": "QR_LIMIT_STR_SCENE",
                    "action_info": {"scene": {"scene_str": scene_str}},
                }
            )
        except Exception as exc:
            raise ValidationError(f"微信接口调用失败：{exc}")

        ticket = res.get("ticket")
        if not ticket:
            raise ValidationError("二维码生成失败，请稍后再试")
        return wechat_client.qrcode.get_url(ticket)

    @classmethod
    def get_sales_qrcode_url(cls, sales_profile: "SalesProfile") -> str:
        """
        获取销售二维码链接，先读缓存，缺失时懒加载生成。
        """

        if not sales_profile:
            raise ValidationError("缺少销售档案信息。")

        if sales_profile.qrcode_url:
            return sales_profile.qrcode_url

        qrcode_url = cls.generate_permanent_qrcode(sales_profile.pk)
        sales_profile.qrcode_url = qrcode_url
        sales_profile.save(update_fields=["qrcode_url", "updated_at"])
        return qrcode_url
