from django.test import TestCase, override_settings
from django.urls import reverse
from users.models import CustomUser, PatientProfile
from users import choices
from unittest.mock import patch
import re
from market.models import Product, Order
from decimal import Decimal
from django.utils import timezone
from datetime import timedelta

@override_settings(DEBUG=True, TEST_PATIENT_ID="1")
class PatientHomeUnreadBadgeTests(TestCase):
  def setUp(self):
    self.user = CustomUser.objects.create_user(
      username="unread_badge_user",
      password="password",
      user_type=choices.UserType.PATIENT,
      wx_openid="test_openid_unread_badge",
    )
    self.patient = PatientProfile.objects.create(
      user=self.user,
      name="未读徽章测试患者",
      phone="13800000001",
    )
    self.client.force_login(self.user)
    product = Product.objects.create(
      name="VIP 服务包",
      price=Decimal("199.00"),
      duration_days=30,
      is_active=True,
    )
    Order.objects.create(
      patient=self.patient,
      product=product,
      amount=Decimal("199.00"),
      status=Order.Status.PAID,
      paid_at=timezone.now(),
    )

  def _get_home_html(self):
    response = self.client.get(reverse("web_patient:patient_home"))
    self.assertEqual(response.status_code, 200)
    return response.content.decode("utf-8")

  @patch("web_patient.views.chat_api.get_unread_chat_count", return_value=0)
  def test_badge_hidden_when_unread_zero(self, mock_func):
    html = self._get_home_html()
    self.assertIn('id="unread-badge"', html)
    self.assertIn('style="display:none"', html)

  @patch("web_patient.views.chat_api.get_unread_chat_count", return_value=1)
  def test_badge_shows_one(self, mock_func):
    html = self._get_home_html()
    self.assertIn('id="unread-badge"', html)
    self.assertRegex(html, r'id="unread-badge".*?>\s*1\s*<')

  @patch("web_patient.views.chat_api.get_unread_chat_count", return_value=99)
  def test_badge_shows_ninety_nine(self, mock_func):
    html = self._get_home_html()
    self.assertIn('id="unread-badge"', html)
    self.assertRegex(html, r'id="unread-badge".*?>\s*99\s*<')

  @patch("web_patient.views.chat_api.get_unread_chat_count", return_value=100)
  def test_badge_shows_overflow(self, mock_func):
    html = self._get_home_html()
    self.assertIn("99+", html)

  @patch("web_patient.views.chat_api.get_unread_chat_count", side_effect=Exception("network error"))
  def test_badge_handles_exception_default_zero(self, mock_func):
    html = self._get_home_html()
    self.assertIn('id="unread-badge"', html)
    self.assertIn('style="display:none"', html)
