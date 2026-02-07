import json
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model
from users.choices import UserType, RelationType
from users.models import PatientProfile, DoctorProfile, DoctorStudio, PatientRelation
from chat.models import Conversation, ConversationType, Message, MessageSenderRole, PatientStudioAssignment

User = get_user_model()


class DoctorChatFamilyNameFormatTests(TestCase):
  def setUp(self):
    self.client = Client()
    # 医生与工作室
    self.doctor_user = User.objects.create_user(
      username="doctor_family_format",
      password="password",
      user_type=UserType.DOCTOR,
      phone="13800000011",
    )
    self.director_profile = DoctorProfile.objects.create(user=self.doctor_user, name="主任X")
    self.studio = DoctorStudio.objects.create(name="格式工作室", owner_doctor=self.director_profile)
    self.director_profile.studio = self.studio
    self.director_profile.save()

    # 患者与家属
    self.patient_user = User.objects.create_user(
      username="patient_family_format",
      password="password",
      user_type=UserType.PATIENT,
      wx_openid="openid_pf_1",
    )
    self.patient = PatientProfile.objects.create(user=self.patient_user, name="患者Y", phone="13900000002")
    PatientStudioAssignment.objects.create(patient=self.patient, studio=self.studio, start_at=timezone.now())

    self.family_user = User.objects.create_user(
      username="family_family_format",
      password="password",
      user_type=UserType.PATIENT,
      wx_openid="wx_oR9yO2KN",  # 模拟微信标识
    )
    PatientRelation.objects.create(
      patient=self.patient,
      user=self.family_user,
      relation_type=RelationType.SPOUSE,
      name="张鹏爱人",
      relation_name="配偶",
      is_active=True,
    )

    # 会话与消息（模拟历史快照为“wx标识(家属姓名)”）
    self.conversation = Conversation.objects.create(
      type=ConversationType.PATIENT_STUDIO,
      patient=self.patient,
      studio=self.studio,
      created_by=self.doctor_user,
    )
    self.family_msg = Message.objects.create(
      conversation=self.conversation,
      sender=self.family_user,
      sender_role_snapshot=MessageSenderRole.FAMILY,
      sender_display_name_snapshot="wx_oR9yO2KN(张鹏爱人)",
      studio_name_snapshot=self.studio.name,
      content_type=MessageSenderRole.PATIENT,  # 无关字段占位
      text_content="家属咨询",
    )
    self.patient_msg = Message.objects.create(
      conversation=self.conversation,
      sender=self.patient_user,
      sender_role_snapshot=MessageSenderRole.PATIENT,
      sender_display_name_snapshot="患者Y",
      studio_name_snapshot=self.studio.name,
      text_content="患者补充",
    )

    self.client.login(username="doctor_family_format", password="password")
    self.list_url = reverse("web_doctor:chat_api_list_messages")

  def test_family_sender_name_normalized(self):
    resp = self.client.get(self.list_url, {"conversation_id": self.conversation.id})
    self.assertEqual(resp.status_code, 200)
    data = resp.json()
    self.assertEqual(data["status"], "success")
    msgs = data["messages"]
    fam = next(m for m in msgs if m["id"] == self.family_msg.id)
    self.assertEqual(fam["sender_role"], MessageSenderRole.FAMILY)
    # 规范化后仅显示“姓名(关系)”
    self.assertEqual(fam["sender_name"], "张鹏爱人(配偶)")
    # 普通患者不受影响
    pat = next(m for m in msgs if m["id"] == self.patient_msg.id)
    self.assertEqual(pat["sender_name"], "患者Y")

