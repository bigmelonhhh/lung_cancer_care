from decimal import Decimal

from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from market.models import Order, Product
from users import choices
from users.models import CustomUser, PatientProfile


@override_settings(DEBUG=True, TEST_PATIENT_ID="1")
class MembershipAccessTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username="member_access_user",
            password="password",
            user_type=choices.UserType.PATIENT,
            wx_openid="test_openid_member_access",
        )
        self.patient = PatientProfile.objects.create(
            user=self.user,
            name="会员测试患者",
            phone="13800000000",
        )
        self.client.force_login(self.user)

    def _create_paid_membership_order(self, paid_at=None):
        product = Product.objects.create(
            name="VIP 服务包",
            price=Decimal("199.00"),
            duration_days=30,
            is_active=True,
        )
        return Order.objects.create(
            patient=self.patient,
            product=product,
            amount=Decimal("199.00"),
            status=Order.Status.PAID,
            paid_at=paid_at or timezone.now(),
        )

    def test_patient_home_non_member_short_circuit(self):
        response = self.client.get(reverse("web_patient:patient_home"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["is_member"])
        self.assertEqual(response.context["service_days"], "0")
        self.assertEqual(response.context["daily_plans"], [])

    def test_patient_home_member_flag_true(self):
        self._create_paid_membership_order()
        response = self.client.get(reverse("web_patient:patient_home"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["is_member"])

    def test_non_member_cannot_access_management_plan(self):
        response = self.client.get(reverse("web_patient:management_plan"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].endswith(reverse("market:product_buy")))

    def test_non_member_cannot_access_my_medication(self):
        response = self.client.get(reverse("web_patient:my_medication"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].endswith(reverse("market:product_buy")))

    def test_query_last_metric_non_member_returns_empty(self):
        response = self.client.get(reverse("web_patient:query_last_metric"))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["plans"], {})

