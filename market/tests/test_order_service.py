"""Order service tests."""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from market.models import Order, Product
from market.service.order import get_paid_orders_for_patient
from users.models import PatientProfile


class OrderServiceTest(TestCase):
    """验证订单服务的已支付订单查询逻辑。"""

    def setUp(self) -> None:
        self.patient = PatientProfile.objects.create(
            phone="13800000002",
            name="订单测试患者",
        )
        self.other_patient = PatientProfile.objects.create(
            phone="13800000003",
            name="其他患者",
        )
        self.product = Product.objects.create(
            name="测试服务包",
            price=199,
            duration_days=30,
        )

    def test_get_paid_orders_for_patient_filters_paid_and_orders(self):
        now = timezone.now()
        order_recent = Order.objects.create(
            patient=self.patient,
            product=self.product,
            amount=self.product.price,
            status=Order.Status.PAID,
            paid_at=now,
        )
        order_old = Order.objects.create(
            patient=self.patient,
            product=self.product,
            amount=self.product.price,
            status=Order.Status.PAID,
            paid_at=now - timedelta(days=2),
        )
        Order.objects.create(
            patient=self.patient,
            product=self.product,
            amount=self.product.price,
            status=Order.Status.PENDING,
            paid_at=None,
        )
        Order.objects.create(
            patient=self.other_patient,
            product=self.product,
            amount=self.product.price,
            status=Order.Status.PAID,
            paid_at=now - timedelta(days=1),
        )

        orders = get_paid_orders_for_patient(self.patient)

        self.assertEqual([order.id for order in orders], [order_recent.id, order_old.id])
