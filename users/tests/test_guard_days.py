from datetime import timedelta, date

from django.test import TestCase
from django.utils import timezone

from market.models import Order, Product
from users.models import PatientProfile
from users.services.patient import PatientService


class GetGuardDaysTests(TestCase):
    def setUp(self) -> None:
        self.service = PatientService()
        self.patient = PatientProfile.objects.create(
            phone="13800000000",
            name="测试患者",
        )
        self.today = timezone.localdate()

    def _create_order(self, paid_at_delta_days: int, duration_days: int, status=Order.Status.PAID):
        """Helper to create a product and an order."""
        product = Product.objects.create(
            name=f"服务包-{duration_days}天",
            price="100.00",
            duration_days=duration_days,
            is_active=True,
        )
        paid_at = timezone.now() + timedelta(days=paid_at_delta_days) if paid_at_delta_days is not None else None
        
        return Order.objects.create(
            patient=self.patient,
            product=product,
            amount=product.price,
            status=status,
            paid_at=paid_at,
        )

    def test_no_paid_orders_returns_zero(self):
        """没有已支付订单时，已服务和剩余天数都为 0。"""
        served_days, remaining_days = self.service.get_guard_days(self.patient)
        self.assertEqual(served_days, 0)
        self.assertEqual(remaining_days, 0)

    def test_single_order_past_and_future(self):
        """
        单个订单，部分在过去，部分在未来。
        - 支付日: 2天前
        - 持续: 5天
        - 服务区间: [today-2, today+2]
        - 预期的已服务天数: 2 (昨天, 前天)
        - 预期的剩余天数: 3 (今天, 明天, 后天)
        """
        self._create_order(paid_at_delta_days=-2, duration_days=5)
        served_days, remaining_days = self.service.get_guard_days(self.patient)
        self.assertEqual(served_days, 2)
        self.assertEqual(remaining_days, 3)

    def test_fully_past_order(self):
        """单个订单，完全在过去。"""
        self._create_order(paid_at_delta_days=-10, duration_days=4)
        served_days, remaining_days = self.service.get_guard_days(self.patient)
        self.assertEqual(served_days, 4)
        self.assertEqual(remaining_days, 0)

    def test_fully_future_order(self):
        """单个订单，完全在未来。"""
        self._create_order(paid_at_delta_days=5, duration_days=10)
        served_days, remaining_days = self.service.get_guard_days(self.patient)
        self.assertEqual(served_days, 0)
        self.assertEqual(remaining_days, 10)
        
    def test_order_starting_today(self):
        """订单从今天开始。"""
        self._create_order(paid_at_delta_days=0, duration_days=7)
        served_days, remaining_days = self.service.get_guard_days(self.patient)
        self.assertEqual(served_days, 0)
        self.assertEqual(remaining_days, 7)

    def test_overlapped_orders_in_past(self):
        """
        多个重叠订单，都在过去。
        - 订单 A: paid_at=today-5, duration=4 => [today-5, today-2]
        - 订单 B: paid_at=today-4, duration=3 => [today-4, today-2]
        - 合并后区间: [today-5, today-2]
        - 预期已服务天数: 4
        """
        self._create_order(paid_at_delta_days=-5, duration_days=4)
        self._create_order(paid_at_delta_days=-4, duration_days=3)
        served_days, remaining_days = self.service.get_guard_days(self.patient)
        self.assertEqual(served_days, 4)
        self.assertEqual(remaining_days, 0)

    def test_consecutive_orders(self):
        """
        两个订单服务期连续。
        - 订单 A: paid_at=today-5, duration=3 => [today-5, today-3]
        - 订单 B: paid_at=today-2, duration=4 => [today-2, today+1]
        - 合并后区间: [today-5, today+1]
        - 预期已服务天数: 3 (today-5, today-4, today-3)
        - 预期剩余天数: 4 (today-2, today-1, today, today+1) - WRONG
        - 预期已服务天数 (Correct): 5 (today-5, -4, -3, -2, -1)
        - 预期剩余天数 (Correct): 2 (today, today+1)

        """
        order_a_start_date = self.today - timedelta(days=5)
        # To make order_b start date consecutive to order_a end date, we need to know paid_at.
        # Let's define ranges directly for simplicity in test logic.
        # A: ends at today-3. So next one should start at today-2.
        # paid_at for B should be today-2
        self._create_order(paid_at_delta_days=-5, duration_days=3)
        self._create_order(paid_at_delta_days=-2, duration_days=4)

        served_days, remaining_days = self.service.get_guard_days(self.patient)
        # Merged range: [today-5, today-3] U [today-2, today+1] -> [today-5, today+1]
        # Served: from today-5 to yesterday. (today-1) - (today-5) + 1 = 5 days.
        # Remaining: from today to today+1. (today+1) - today + 1 = 2 days.
        self.assertEqual(served_days, 5)
        self.assertEqual(remaining_days, 2)

    def test_non_paid_orders_are_ignored(self):
        """非 PAID 状态的订单不会计入。"""
        self._create_order(paid_at_delta_days=-5, duration_days=10, status=Order.Status.PENDING)
        self._create_order(paid_at_delta_days=-2, duration_days=5, status=Order.Status.CANCELLED)
        served_days, remaining_days = self.service.get_guard_days(self.patient)
        self.assertEqual(served_days, 0)
        self.assertEqual(remaining_days, 0)

    def test_order_with_zero_duration_is_ignored(self):
        """duration_days 为 0 的订单会被忽略。"""
        self._create_order(paid_at_delta_days=-1, duration_days=0)
        served_days, remaining_days = self.service.get_guard_days(self.patient)
        self.assertEqual(served_days, 0)
        self.assertEqual(remaining_days, 0)
        
    def test_complex_scenario_multiple_orders(self):
        """
        复杂场景: 混合过去、未来、重叠、连续的订单。
        1. 订单 A: 10天前支付, 持续5天 -> [today-10, today-6]
        2. 订单 B: 8天前支付, 持续4天 -> [today-8, today-5] (与A重叠/连续)
        3. 订单 C: 1天前支付, 持续5天 -> [today-1, today+3] (跨越今天)
        4. 订单 D: 5天后支付, 持续3天 -> [today+5, today+7]
        
        合并后区间:
        - [today-10, today-5]  (A和B合并)
        - [today-1, today+3]   (C)
        - [today+5, today+7]   (D)
        
        统计:
        - 已服务:
          - from [today-10, today-5]: 6天
          - from [today-1, today+3]: 1天 (昨天)
          - 总计: 7天
        - 剩余:
          - from [today-1, today+3]: 4天 (today..today+3)
          - from [today+5, today+7]: 3天
          - 总计: 7天
        """
        self._create_order(paid_at_delta_days=-10, duration_days=5) # A
        self._create_order(paid_at_delta_days=-8, duration_days=4)  # B
        self._create_order(paid_at_delta_days=-1, duration_days=5)   # C
        self._create_order(paid_at_delta_days=5, duration_days=3)    # D
        
        served_days, remaining_days = self.service.get_guard_days(self.patient)
        self.assertEqual(served_days, 7)
        self.assertEqual(remaining_days, 7)