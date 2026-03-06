import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from chat.models import Message
from chat.services.chat import ChatService
from users import choices
from users.models import (
    AssistantProfile,
    DoctorAssistantMap,
    DoctorProfile,
    DoctorStudio,
    PatientProfile,
)

User = get_user_model()


class MobilePatientChatListTests(TestCase):
    """医生移动端患者咨询列表页测试。"""

    def setUp(self):
        self.service = ChatService()

        self.director_user = User.objects.create_user(
            username="doc_chat_list_director",
            password="password",
            user_type=choices.UserType.DOCTOR,
            phone="13901000001",
        )
        self.director_profile = DoctorProfile.objects.create(
            user=self.director_user,
            name="李主任",
            hospital="市一医院",
            department="肿瘤科",
            title="主任医师",
        )
        self.studio = DoctorStudio.objects.create(
            name="主任工作室",
            code="STU_TEST_CHAT_LIST",
            owner_doctor=self.director_profile,
        )

        self.doctor_user = User.objects.create_user(
            username="doc_chat_list_member",
            password="password",
            user_type=choices.UserType.DOCTOR,
            phone="13901000002",
        )
        self.doctor_profile = DoctorProfile.objects.create(
            user=self.doctor_user,
            name="张医生",
            hospital="市一医院",
            department="肿瘤科",
            title="医师",
            studio=self.studio,
        )

        self.assistant_user = User.objects.create_user(
            username="assistant_chat_list_member",
            password="password",
            user_type=choices.UserType.ASSISTANT,
            phone="13901000005",
        )
        self.assistant_profile = AssistantProfile.objects.create(
            user=self.assistant_user,
            name="平台助理A",
            status=choices.AssistantStatus.ACTIVE,
        )
        DoctorAssistantMap.objects.create(
            doctor=self.doctor_profile,
            assistant=self.assistant_profile,
        )

        self.patient_user = User.objects.create_user(
            username="patient_chat_list",
            password="password",
            user_type=choices.UserType.PATIENT,
            phone="13901000003",
            wx_openid="wx_test_openid_patient_chat_list",
        )
        self.patient_profile = PatientProfile.objects.create(
            user=self.patient_user,
            name="王患者",
            phone="13800123456",
            gender=choices.Gender.FEMALE,
            doctor=self.doctor_profile,
            is_active=True,
        )

        self.conversation = self.service.get_or_create_patient_conversation(
            patient=self.patient_profile,
            studio=self.studio,
            operator=self.doctor_user,
        )

        for i in range(25):
            sender = self.patient_user if i % 2 == 0 else self.doctor_user
            self.service.create_text_message(
                conversation=self.conversation,
                sender=sender,
                content=f"msg-{i}",
            )

        self.mobile_chat_url = reverse(
            "web_doctor:mobile_patient_chat_list", kwargs={"patient_id": self.patient_profile.id}
        )
        self.send_text_url = reverse("web_doctor:chat_api_send_text")

    def test_page_renders_html(self):
        """测试页面可正常渲染并包含标题信息。"""
        self.client.force_login(self.doctor_user)
        response = self.client.get(self.mobile_chat_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "web_doctor/mobile/patient_chat_list.html")
        self.assertContains(response, self.patient_profile.name)

    def test_assistant_page_shows_chat_input_controls(self):
        self.client.force_login(self.assistant_user)
        response = self.client.get(self.mobile_chat_url)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["can_chat"])
        self.assertContains(response, 'data-test="mobile-chat-input"')
        self.assertContains(response, 'data-test="mobile-send-btn"')

    def test_doctor_page_hides_chat_input_controls(self):
        self.client.force_login(self.doctor_user)
        response = self.client.get(self.mobile_chat_url)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["can_chat"])
        self.assertNotContains(response, 'data-test="mobile-chat-input"')
        self.assertNotContains(response, 'data-test="mobile-send-btn"')

    def test_api_paginates_latest_then_older(self):
        """测试接口按时间升序返回最新20条，并支持游标分页加载更早记录。"""
        self.client.force_login(self.doctor_user)
        response = self.client.get(f"{self.mobile_chat_url}?format=json")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("messages", payload)
        self.assertEqual(len(payload["messages"]), 20)
        ids = [m["id"] for m in payload["messages"]]
        self.assertEqual(ids, sorted(ids))
        self.assertTrue(payload["has_next"])
        self.assertTrue(payload["next_cursor"])

        cursor = payload["next_cursor"]
        response2 = self.client.get(f"{self.mobile_chat_url}?format=json&cursor={cursor}")
        self.assertEqual(response2.status_code, 200)
        payload2 = response2.json()
        self.assertEqual(len(payload2["messages"]), 5)
        ids2 = [m["id"] for m in payload2["messages"]]
        self.assertEqual(ids2, sorted(ids2))
        self.assertFalse(payload2["has_next"])
        self.assertFalse(payload2["next_cursor"])

    def test_assistant_can_send_text_message_via_chat_api(self):
        self.client.force_login(self.assistant_user)
        before_count = Message.objects.filter(conversation=self.conversation).count()

        response = self.client.post(
            self.send_text_url,
            data=json.dumps({"conversation_id": self.conversation.id, "content": "助理发送测试"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")

        after_count = Message.objects.filter(conversation=self.conversation).count()
        self.assertEqual(after_count, before_count + 1)
        last_message = Message.objects.filter(conversation=self.conversation).order_by("-id").first()
        self.assertIsNotNone(last_message)
        self.assertEqual(last_message.sender_id, self.assistant_user.id)
        self.assertEqual(last_message.text_content, "助理发送测试")

    def test_director_send_text_to_patient_conversation_is_denied(self):
        self.client.force_login(self.director_user)

        response = self.client.post(
            self.send_text_url,
            data=json.dumps({"conversation_id": self.conversation.id, "content": "主任尝试发送"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertEqual(payload["status"], "error")
        self.assertIn("主任不可在患者会话发言", payload["message"])

    def test_permission_denies_unrelated_doctor(self):
        """测试非绑定医生访问该患者会被拒绝。"""
        other_user = User.objects.create_user(
            username="doc_chat_list_other",
            password="password",
            user_type=choices.UserType.DOCTOR,
            phone="13901000004",
        )
        DoctorProfile.objects.create(
            user=other_user,
            name="其他医生",
            hospital="市二医院",
            department="呼吸科",
            title="医师",
            studio=self.studio,
        )
        self.client.force_login(other_user)
        response = self.client.get(self.mobile_chat_url)
        self.assertEqual(response.status_code, 404)
