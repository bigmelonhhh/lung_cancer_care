from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from market.models import Product, Order
from users import choices
from users.models import CustomUser, PatientProfile


class HealthRecordsMembershipLogicTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = CustomUser.objects.create_user(
            username="testpatient_health_records_membership",
            password="password",
            user_type=choices.UserType.PATIENT,
            wx_openid="test_openid_health_records_membership",
        )
        self.patient = PatientProfile.objects.create(user=self.user, name="Test Patient")
        self.client.force_login(self.user)

    def _create_paid_order(self):
        product = Product.objects.create(
            name="VIP 服务包", price=Decimal("199.00"), duration_days=30, is_active=True
        )
        return Order.objects.create(
            patient=self.patient,
            product=product,
            amount=Decimal("199.00"),
            status=Order.Status.PAID,
            paid_at=timezone.now(),
        )

    def test_non_member_health_records_returns_empty_member_modules(self):
        response = self.client.get(reverse("web_patient:health_records"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["is_member"])
        self.assertEqual(response.context["service_packages"], [])
        self.assertEqual(response.context["checkup_stats"], [])
        self.assertEqual(response.context["health_survey_stats"], [])
        self.assertTrue(len(response.context["health_stats"]) > 0)

    def test_member_health_records_returns_member_modules(self):
        self._create_paid_order()
        response = self.client.get(reverse("web_patient:health_records"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["is_member"])
        self.assertTrue(len(response.context["service_packages"]) > 0)
        self.assertTrue(len(response.context["health_survey_stats"]) > 0)

    def test_membership_status_endpoint(self):
        status_url = reverse("web_patient:membership_status")
        resp = self.client.get(status_url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertFalse(data["is_member"])

        self._create_paid_order()
        resp2 = self.client.get(status_url)
        self.assertEqual(resp2.status_code, 200)
        data2 = resp2.json()
        self.assertTrue(data2["success"])
        self.assertTrue(data2["is_member"])

