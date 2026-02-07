import json
from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from users.models import CustomUser, PatientProfile
from users import choices
from market.models import Product, Order
from users.models import DoctorProfile, DoctorStudio
from chat.models import PatientStudioAssignment
from chat.services.chat import ChatService

class HomeUnreadFlowTests(TestCase):
  def setUp(self):
    self.user = CustomUser.objects.create_user(
      username="unread_flow_user",
      password="password",
      user_type=choices.UserType.PATIENT,
      wx_openid="test_openid_unread_flow",
    )
    self.patient = PatientProfile.objects.create(
      user=self.user,
      name="未读流程患者",
      phone="13800000002",
    )
    self.client.force_login(self.user)
    self.home_url = reverse("web_patient:patient_home")
    self.unread_count_url = reverse("web_patient:chat_api_unread_count")
    self.reset_unread_url = reverse("web_patient:chat_api_reset_unread")
    self.doctor_user = CustomUser.objects.create_user(
      username="doc_unread_flow",
      password="password",
      user_type=choices.UserType.DOCTOR,
      phone="13800000003",
    )
    self.doctor_profile = DoctorProfile.objects.create(user=self.doctor_user, name="医生A")
    self.studio = DoctorStudio.objects.create(name="工作室A", owner_doctor=self.doctor_profile)
    self.doctor_profile.studio = self.studio
    self.doctor_profile.save()
    PatientStudioAssignment.objects.create(
      patient=self.patient,
      studio=self.studio,
      start_at=timezone.now()
    )

  def _enable_membership(self):
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

  def test_home_unread_gating_non_member(self):
    resp = self.client.get(self.home_url)
    self.assertEqual(resp.status_code, 200)
    self.assertEqual(resp.context["unread_chat_count"], 0)

  def test_home_unread_gating_member_and_reset(self):
    self._enable_membership()
    svc = ChatService()
    conv = svc.get_or_create_patient_conversation(self.patient)
    doc_user2 = CustomUser.objects.create_user(
      username="doc_member_flow",
      password="password",
      user_type=choices.UserType.DOCTOR,
      phone="13800000004",
    )
    doc_profile2 = DoctorProfile.objects.create(user=doc_user2, name="医生B", studio=self.studio)
    svc.create_text_message(conv, doc_user2, "消息1")
    resp = self.client.get(self.home_url)
    self.assertEqual(resp.status_code, 200)
    self.assertTrue(resp.context["is_member"])
    self.assertGreaterEqual(resp.context["unread_chat_count"], 1)
    resp = self.client.get(self.unread_count_url)
    self.assertEqual(resp.status_code, 200)
    data = resp.json()
    self.assertEqual(data["status"], "success")
    self.assertGreaterEqual(data["count"], 1)
    resp = self.client.post(self.reset_unread_url, json.dumps({}), content_type="application/json")
    self.assertEqual(resp.status_code, 200)
    resp = self.client.get(self.unread_count_url)
    data = resp.json()
    self.assertEqual(data["count"], 0)
