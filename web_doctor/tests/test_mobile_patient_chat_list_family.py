import json
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model
from users.choices import UserType, RelationType
from users.models import PatientProfile, DoctorProfile, DoctorStudio, PatientRelation
from chat.models import Conversation, ConversationType, Message, MessageSenderRole, PatientStudioAssignment

User = get_user_model()


class MobilePatientChatListFamilyTests(TestCase):
  def setUp(self):
    self.client = Client()
    # 医生与工作室
    self.doctor_user = User.objects.create_user(
      username="doctor_mobile_family",
      password="password",
      user_type=UserType.DOCTOR,
      phone="13800000021",
    )
    self.director_profile = DoctorProfile.objects.create(user=self.doctor_user, name="主任M")
    self.studio = DoctorStudio.objects.create(name="移动工作室", owner_doctor=self.director_profile)
    self.director_profile.studio = self.studio
    self.director_profile.save()

    # 患者与家属
    self.patient_user = User.objects.create_user(
      username="patient_mobile_family",
      password="password",
      user_type=UserType.PATIENT,
      wx_openid="openid_mobile_pf_1",
    )
    self.patient = PatientProfile.objects.create(user=self.patient_user, name="患者Z", phone="13900000022", doctor=self.director_profile)
    PatientStudioAssignment.objects.create(patient=self.patient, studio=self.studio, start_at=timezone.now())

    self.family_user = User.objects.create_user(
      username="family_mobile_sender",
      password="password",
      user_type=UserType.PATIENT,
      wx_openid="wx_mobile_123",
    )
    PatientRelation.objects.create(
      patient=self.patient,
      user=self.family_user,
      relation_type=RelationType.PARENT,
      name="张父亲",
      relation_name="父亲",
      is_active=True,
    )

    # 会话与消息（家属 + 患者）
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
      sender_display_name_snapshot="wx_mobile_123(张父亲)",
      studio_name_snapshot=self.studio.name,
      text_content="家属移动端咨询",
    )
    self.patient_msg = Message.objects.create(
      conversation=self.conversation,
      sender=self.patient_user,
      sender_role_snapshot=MessageSenderRole.PATIENT,
      sender_display_name_snapshot="患者Z",
      studio_name_snapshot=self.studio.name,
      text_content="患者移动端补充",
    )

    self.client.login(username="doctor_mobile_family", password="password")
    self.list_url = reverse("web_doctor:mobile_patient_chat_list", kwargs={"patient_id": self.patient.id})

  def test_mobile_patient_chat_list_json_family_name_normalized(self):
    resp = self.client.get(f"{self.list_url}?format=json")
    self.assertEqual(resp.status_code, 200)
    payload = resp.json()
    msgs = payload["messages"]
    fam = next(m for m in msgs if m["id"] == self.family_msg.id)
    self.assertEqual(fam["sender_role"], MessageSenderRole.FAMILY)
    self.assertEqual(fam["sender_name"], "张父亲(父亲)")
    pat = next(m for m in msgs if m["id"] == self.patient_msg.id)
    self.assertEqual(pat["sender_name"], "患者Z")
