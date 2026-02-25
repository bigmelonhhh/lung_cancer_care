import json
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone
from users.choices import UserType, RelationType
from users.models import PatientProfile, DoctorProfile, DoctorStudio, PatientRelation
from chat.services.chat import ChatService
from chat.models import MessageSenderRole, PatientStudioAssignment

User = get_user_model()


class PatientFamilyChatDisplayTests(TestCase):
  def setUp(self):
    self.client = Client()
    # 患者与家属
    self.patient_user = User.objects.create_user(
      username="patient_viewer",
      password="password",
      user_type=UserType.PATIENT,
      wx_openid="openid_patient_1",
    )
    self.patient = PatientProfile.objects.create(
      user=self.patient_user, name="患者甲", phone="13900000001"
    )
    self.family_user = User.objects.create_user(
      username="family_sender",
      password="password",
      user_type=UserType.PATIENT,
      wx_openid="openid_family_1",
    )
    PatientRelation.objects.create(
      patient=self.patient,
      user=self.family_user,
      relation_type=RelationType.SPOUSE,
      name="家属乙",
      relation_name="配偶",
      is_active=True,
    )
    # 医生与工作室
    self.doctor_user = User.objects.create_user(
      username="doctor_reply",
      password="password",
      user_type=UserType.DOCTOR,
      phone="13800000001",
    )
    # 创建主任作为工作室拥有者，医生丁为平台医生
    self.director_user = User.objects.create_user(
      username="director_owner",
      password="password",
      user_type=UserType.DOCTOR,
      phone="13800000002",
    )
    self.director_profile = DoctorProfile.objects.create(
      user=self.director_user, name="主任甲"
    )
    self.studio = DoctorStudio.objects.create(
      name="肿瘤科工作室", owner_doctor=self.director_profile
    )
    self.doctor_profile = DoctorProfile.objects.create(
      user=self.doctor_user, name="医生丁", studio=self.studio
    )

    # 归属与会话
    PatientStudioAssignment.objects.create(
      patient=self.patient, studio=self.studio, start_at=timezone.now()
    )
    self.service = ChatService()
    self.conversation = self.service.get_or_create_patient_conversation(self.patient)

    # 预置消息：家属 -> 医生；医生 -> 家属
    self.family_msg = self.service.create_text_message(
      self.conversation, self.family_user, "家属咨询内容A"
    )
    self.doctor_msg = self.service.create_text_message(
      self.conversation, self.doctor_user, "医生回复内容B"
    )

    # URL
    self.patient_list_url = reverse("web_patient:chat_api_list_messages")
    self.doctor_list_url = reverse("web_doctor:chat_api_list_messages")

  def test_patient_view_family_message_fields(self):
    self.client.login(username="patient_viewer", password="password")
    # 确保中间件使用该患者上下文
    session = self.client.session
    session["active_patient_id"] = self.patient.id
    session.save()

    resp = self.client.get(self.patient_list_url)
    self.assertEqual(resp.status_code, 200)
    payload = resp.json()
    self.assertEqual(payload["status"], "success")
    msgs = payload["messages"]
    self.assertEqual(len(msgs), 2)
    # 家属消息校验
    fm = msgs[0]
    self.assertEqual(fm["id"], self.family_msg.id)
    self.assertEqual(fm["sender_role"], MessageSenderRole.FAMILY)
    self.assertTrue(fm["is_patient_side"])
    self.assertIn("家属乙", fm["sender_name"])
    self.assertIn("配偶", fm["sender_name"])
    self.assertEqual(fm["text_content"], "家属咨询内容A")
    # 医生消息校验
    dm = msgs[1]
    self.assertEqual(dm["id"], self.doctor_msg.id)
    self.assertFalse(dm["is_patient_side"])
    self.assertEqual(dm["sender_name"], self.studio.name)
    self.assertEqual(dm["text_content"], "医生回复内容B")

  def test_family_view_same_conversation_patient_side_flag(self):
    self.client.login(username="family_sender", password="password")
    session = self.client.session
    session["active_patient_id"] = self.patient.id
    session.save()

    resp = self.client.get(self.patient_list_url)
    self.assertEqual(resp.status_code, 200)
    msgs = resp.json()["messages"]
    # 家属视角下，患者侧标记仍为 true
    fm = next(m for m in msgs if m["id"] == self.family_msg.id)
    self.assertTrue(fm["is_patient_side"])
    dm = next(m for m in msgs if m["id"] == self.doctor_msg.id)
    self.assertFalse(dm["is_patient_side"])

  def test_doctor_view_sender_name_snapshot(self):
    self.client.login(username="doctor_reply", password="password")
    resp = self.client.get(
      self.doctor_list_url, {"conversation_id": self.conversation.id}
    )
    self.assertEqual(resp.status_code, 200)
    data = resp.json()
    self.assertEqual(data["status"], "success")
    msgs = data["messages"]
    # 医生端序列化不返回 is_patient_side，保持契约
    self.assertNotIn("is_patient_side", msgs[0])
    # 名称使用快照：家属消息包含家属姓名与关系
    fm = next(m for m in msgs if m["id"] == self.family_msg.id)
    self.assertIn("家属乙", fm["sender_name"])
    self.assertIn("配偶", fm["sender_name"])
    # 医生消息包含医生姓名
    dm = next(m for m in msgs if m["id"] == self.doctor_msg.id)
    self.assertIn("医生丁", dm["sender_name"])
