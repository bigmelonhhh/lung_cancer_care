"""
订单与支付相关的领域服务。

【设计说明】
- 该模块封装与服务包购买相关的核心业务逻辑，视图层只负责 HTTP 解析与响应。
- 一个业务一个方法，便于单元测试和复用。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time

from django.db import transaction
from django.utils import timezone

import markdown

from market.models import Order, Product
from users.models import CustomUser, PatientProfile
from wx.services.pay import create_jsapi_params

logger = logging.getLogger(__name__)


class OrderBusinessError(Exception):
    """订单相关业务异常基类。"""


class ProductNotAvailableError(OrderBusinessError):
    """商品不存在或未上架。"""


class PatientMissingError(OrderBusinessError):
    """当前账号未绑定患者档案。"""


class OpenIDMissingError(OrderBusinessError):
    """微信 OpenID 缺失，无法发起支付。"""


class PaymentNotifyError(OrderBusinessError):
    """支付回调业务异常。"""


@dataclass(frozen=True)
class OrderCreateResult:
    """
    【业务说明】创建订单及支付参数的返回结果。
    【用法】前端调用下单接口时使用，携带订单与微信 JSAPI 参数。
    """

    order: Order
    pay_params: dict


def get_product_for_buy(product_id: str | int | None) -> Product:
    """
    【业务说明】根据前端传入的 product_id 获取可购买的服务包。
    【用法】
    - 购买页加载时调用；
    - 若传入 product_id，则返回对应上架商品；
    - 若未传入，则返回第一个上架商品。
    【参数】
    - product_id: 商品主键 ID，可为空或字符串形式。
    【返回值】
    - 可购买的 Product 实例。
    【异常】
    - Product.DoesNotExist: 当指定商品不存在或当前无上架商品时抛出。
    """

    qs = Product.objects.filter(is_active=True)
    if product_id:
        return qs.get(pk=product_id)
    product = qs.order_by("id").first()
    if not product:
        raise Product.DoesNotExist("当前没有可购买的服务包")
    return product


def render_service_content_markdown(source: str | None) -> str:
    """
    【业务说明】将服务包内容从 Markdown 文本渲染为 HTML。
    【用法】
    - 后台运营在 Admin 中以 Markdown 录入；
    - 展示页调用本方法得到安全的 HTML 片段。
    【参数】
    - source: Markdown 文本，可为空。
    【返回值】
    - 渲染后的 HTML 字符串。
    """

    return markdown.markdown(source or "", extensions=["extra"])


def create_order_for_user(
    *,
    user: CustomUser,
    product_id: int,
    client_ip: str,
) -> OrderCreateResult:
    """
    【业务说明】为当前微信患者创建待支付订单，并生成微信 JSAPI 支付参数。
    【用法】
    - 患者在前端勾选协议后点击“立即购买”；
    - 视图层调用本方法完成订单创建与统一下单。
    【参数】
    - user: 当前登录的 CustomUser 实例，要求已绑定 patient_profile 与 wx_openid。
    - product_id: 购买的服务包 ID。
    - client_ip: 发起请求的客户端 IP，用于微信下单。
    【返回值】
    - OrderCreateResult，包含新建订单与微信 JSAPI 参数。
    【异常】
    - ProductNotAvailableError: 商品不存在或未上架。
    - PatientMissingError: 未找到关联的患者档案。
    - OpenIDMissingError: 当前账号缺少 wx_openid。
    - OrderBusinessError: 微信下单失败等内部错误。
    """

    try:
        product = Product.objects.get(pk=product_id, is_active=True)
    except Product.DoesNotExist as exc:
        raise ProductNotAvailableError("商品不存在或已下架") from exc

    try:
        patient: PatientProfile = user.patient_profile  # OneToOne 反向关联
    except PatientProfile.DoesNotExist as exc:
        raise PatientMissingError("当前账号尚未关联患者档案") from exc

    openid = user.wx_openid
    if not openid:
        raise OpenIDMissingError("缺少微信 OpenID，无法发起支付")

    try:
        with transaction.atomic():
            order = Order.objects.create(
                patient=patient,
                product=product,
                amount=product.price,
                status=Order.Status.PENDING,
            )

            pay_params = create_jsapi_params(
                openid=openid,
                order_no=order.order_no,
                amount=order.amount,
                body=f"岱劲健康-{product.name}",
                client_ip=client_ip,
            )
    except Exception as exc:  # pragma: no cover - 网络或第三方异常
        logger.exception("创建订单或调用微信下单失败: %s", exc)
        raise OrderBusinessError("创建订单失败，请稍后重试") from exc

    return OrderCreateResult(order=order, pay_params=pay_params)


def handle_wechat_pay_success(data: dict) -> Order:
    """
    【业务说明】处理微信支付异步通知，更新订单状态。
    【用法】
    - 支付回调视图在完成验签后，调用本方法执行订单状态流转。
    【参数】
    - data: 通过 verify_notify 解析后的回调数据字典。
    【返回值】
    - 更新后的 Order 实例。
    【异常】
    - PaymentNotifyError: 业务上认为回调无效（缺少订单号、支付未成功等）。
    - Order.DoesNotExist: 找不到对应订单。
    """

    result_code = data.get("result_code")
    out_trade_no = data.get("out_trade_no")

    if not out_trade_no:
        raise PaymentNotifyError("缺少订单号")

    if result_code != "SUCCESS":
        raise PaymentNotifyError("支付未成功")

    with transaction.atomic():
        order = (
            Order.objects.select_for_update()
            .select_related("product", "patient")
            .get(order_no=out_trade_no)
        )
        if order.status == Order.Status.PENDING:
            order.status = Order.Status.PAID
            order.paid_at = order.paid_at or timezone.now()
            order.save(update_fields=["status", "paid_at", "updated_at"])
        if order.status == Order.Status.PAID:
            _update_patient_membership_expire_at(order)
    return order


def _update_patient_membership_expire_at(order: Order) -> None:
    """支付成功后，更新患者会员到期时间（取最大有效期）。"""

    duration_days = getattr(order.product, "duration_days", 0) or 0
    if duration_days <= 0:
        return

    end_date = order.end_date
    if not end_date:
        return

    expire_at = datetime.combine(end_date, time.max)
    if timezone.is_aware(timezone.now()) and timezone.is_naive(expire_at):
        expire_at = timezone.make_aware(expire_at, timezone.get_current_timezone())

    patient = order.patient
    current_expire_at = patient.membership_expire_at
    if current_expire_at and timezone.is_naive(current_expire_at) and timezone.is_aware(expire_at):
        current_expire_at = timezone.make_aware(
            current_expire_at, timezone.get_current_timezone()
        )

    if not current_expire_at or expire_at > current_expire_at:
        patient.membership_expire_at = expire_at
        patient.save(update_fields=["membership_expire_at", "updated_at"])


def get_paid_orders_for_patient(patient: PatientProfile) -> list[Order]:
    """
    获取患者已支付的服务包订单列表。

    【功能说明】
    - 仅返回已支付（paid_at 非空）的订单；
    - 默认按支付时间倒序排列。

    【使用方法】
    - get_paid_orders_for_patient(patient)

    【参数说明】
    - patient: PatientProfile 实例。

    【返回值说明】
    - List[Order]。
    """
    return list(
        Order.objects.filter(patient=patient, paid_at__isnull=False)
        .select_related("product")
        .order_by("-paid_at")
    )
