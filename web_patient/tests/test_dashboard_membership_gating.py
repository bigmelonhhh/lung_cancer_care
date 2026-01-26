from decimal import Decimal

from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone

from market.models import Order, Product
from users import choices
from users.models import CustomUser, PatientProfile


@override_settings(DEBUG=True, TEST_PATIENT_ID="1")
class DashboardMembershipGatingTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = CustomUser.objects.create_user(
            username="testpatient_dashboard_gating",
            password="password",
            user_type=choices.UserType.PATIENT,
            wx_openid="test_openid_dashboard_gating",
        )
        self.patient = PatientProfile.objects.create(
            user=self.user,
            name="Test Patient",
            phone="13800000003",
        )
        self.client.force_login(self.user)

    def _create_paid_order(self):
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
            paid_at=timezone.now(),
        )

    def test_dashboard_non_member_hides_member_urls(self):
        resp = self.client.get(reverse("web_patient:patient_dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context["is_member"])
        content = resp.content.decode()

        self.assertNotIn(reverse("web_patient:my_followup"), content)
        self.assertNotIn(reverse("web_patient:my_examination"), content)
        self.assertNotIn(reverse("web_patient:my_medication"), content)
        self.assertNotIn(reverse("web_patient:orders"), content)
        self.assertNotIn(reverse("web_patient:device_list"), content)
        self.assertNotIn(reverse("web_patient:my_studio"), content)
        self.assertNotIn(reverse("web_patient:report_list"), content)
        self.assertNotIn(reverse("web_patient:family_management"), content)
        self.assertNotIn(reverse("web_patient:feedback"), content)

    def test_dashboard_member_shows_member_urls(self):
        self._create_paid_order()
        resp = self.client.get(reverse("web_patient:patient_dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["is_member"])
        content = resp.content.decode()

        self.assertIn(reverse("web_patient:my_followup"), content)
        self.assertIn(reverse("web_patient:my_examination"), content)
        self.assertIn(reverse("web_patient:my_medication"), content)

    def test_non_member_member_only_views_redirect_to_buy(self):
        buy_path = reverse("market:product_buy")

        resp = self.client.get(reverse("web_patient:my_followup"))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["Location"].endswith(buy_path))

        resp = self.client.get(reverse("web_patient:my_examination"))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["Location"].endswith(buy_path))

        resp = self.client.get(reverse("web_patient:orders"))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["Location"].endswith(buy_path))

        resp = self.client.get(reverse("web_patient:device_list"))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["Location"].endswith(buy_path))

        resp = self.client.get(reverse("web_patient:my_studio"))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["Location"].endswith(buy_path))

        resp = self.client.get(reverse("web_patient:report_list"))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["Location"].endswith(buy_path))

        resp = self.client.get(reverse("web_patient:family_management"))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["Location"].endswith(buy_path))

        resp = self.client.get(reverse("web_patient:feedback"))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["Location"].endswith(buy_path))

    def test_member_can_access_member_only_views(self):
        self._create_paid_order()

        resp = self.client.get(reverse("web_patient:my_followup"))
        self.assertEqual(resp.status_code, 200)

        resp = self.client.get(reverse("web_patient:my_examination"))
        self.assertEqual(resp.status_code, 200)

