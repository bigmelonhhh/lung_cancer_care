import json

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from chat.models import Conversation, ConversationReadState, Message
from chat.models.choices import ConversationType, MessageContentType
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
        self.mobile_internal_chat_url = reverse(
            "web_doctor:mobile_patient_internal_chat", kwargs={"patient_id": self.patient_profile.id}
        )
        self.send_text_url = reverse("web_doctor:chat_api_send_text")
        self.upload_image_url = reverse("web_doctor:chat_api_upload_image")
        self.list_messages_url = reverse("web_doctor:chat_api_list_messages")
        self.mark_read_url = reverse("web_doctor:chat_api_mark_read")

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
        self.assertContains(response, 'data-test="mobile-internal-chat-fab"')
        self.assertContains(response, "联系主任")

    def test_disabled_assistant_page_hides_patient_chat_input_controls(self):
        self.assistant_profile.patient_chat_permission = (
            choices.AssistantPatientChatPermission.DISABLED
        )
        self.assistant_profile.save(update_fields=["patient_chat_permission"])

        self.client.force_login(self.assistant_user)
        response = self.client.get(self.mobile_chat_url)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["can_chat"])
        self.assertNotContains(response, 'data-test="mobile-chat-input"')
        self.assertNotContains(response, 'data-test="mobile-send-btn"')
        self.assertContains(response, 'data-test="mobile-internal-chat-fab"')

    def test_doctor_page_hides_chat_input_controls(self):
        self.client.force_login(self.doctor_user)
        response = self.client.get(self.mobile_chat_url)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["can_chat"])
        self.assertNotContains(response, 'data-test="mobile-chat-input"')
        self.assertNotContains(response, 'data-test="mobile-send-btn"')
        self.assertNotContains(response, 'data-test="mobile-internal-chat-fab"')

    def test_director_page_shows_internal_chat_fab(self):
        self.client.force_login(self.director_user)
        response = self.client.get(self.mobile_chat_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-test="mobile-internal-chat-fab"')
        self.assertContains(response, "联系助理")

    def test_internal_chat_page_allows_director(self):
        self.client.force_login(self.director_user)
        response = self.client.get(self.mobile_internal_chat_url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "web_doctor/mobile/patient_internal_chat.html")
        self.assertTrue(response.context["can_chat"])
        self.assertContains(response, 'data-test="mobile-internal-chat-input"')
        self.assertContains(response, 'data-test="mobile-internal-send-btn"')
        self.assertEqual(response.context["counterpart_label"], "医生助理")

        conversation = Conversation.objects.get(pk=response.context["conversation_id"])
        self.assertEqual(conversation.type, ConversationType.INTERNAL)

    def test_internal_chat_page_allows_assistant(self):
        self.client.force_login(self.assistant_user)
        response = self.client.get(self.mobile_internal_chat_url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "web_doctor/mobile/patient_internal_chat.html")
        self.assertTrue(response.context["can_chat"])
        self.assertEqual(response.context["counterpart_label"], self.director_profile.name)

        conversation = Conversation.objects.get(pk=response.context["conversation_id"])
        self.assertEqual(conversation.type, ConversationType.INTERNAL)

    def test_internal_chat_page_denies_non_director_doctor(self):
        self.client.force_login(self.doctor_user)
        response = self.client.get(self.mobile_internal_chat_url)
        self.assertEqual(response.status_code, 403)

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

    def test_assistant_cannot_view_old_studio_chat_after_doctor_moves_studio(self):
        """医生换工作室后，医助不能通过旧患者聊天 URL 读取旧工作室历史消息。"""
        new_studio = DoctorStudio.objects.create(
            name="新工作室",
            code="TCL_NEW",
            owner_doctor=self.director_profile,
        )
        self.doctor_profile.studio = new_studio
        self.doctor_profile.save(update_fields=["studio"])

        self.client.force_login(self.assistant_user)
        response = self.client.get(self.mobile_chat_url)

        self.assertIn(response.status_code, (403, 404))
        self.assertNotContains(response, "msg-24", status_code=response.status_code)
        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.studio_id, self.studio.id)

    def test_assistant_cannot_page_old_studio_chat_after_doctor_moves_studio(self):
        """医生换工作室后，移动端 JSON 分页也不能读取旧工作室历史消息。"""
        new_studio = DoctorStudio.objects.create(
            name="新工作室2",
            code="TCL_NEW2",
            owner_doctor=self.director_profile,
        )
        self.doctor_profile.studio = new_studio
        self.doctor_profile.save(update_fields=["studio"])

        self.client.force_login(self.assistant_user)
        response = self.client.get(f"{self.mobile_chat_url}?format=json")

        self.assertIn(response.status_code, (403, 404))
        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.studio_id, self.studio.id)

    def test_assistant_cannot_use_message_api_or_mark_read_for_old_studio_after_doctor_moves(self):
        """PC/移动共用消息 API 和已读接口都应拒绝已失去工作室权限的医助。"""
        new_studio = DoctorStudio.objects.create(
            name="新工作室3",
            code="TCL_NEW3",
            owner_doctor=self.director_profile,
        )
        self.doctor_profile.studio = new_studio
        self.doctor_profile.save(update_fields=["studio"])
        latest_message = Message.objects.filter(conversation=self.conversation).order_by("-id").first()

        self.client.force_login(self.assistant_user)
        list_response = self.client.get(
            self.list_messages_url,
            {"conversation_id": self.conversation.id},
        )
        read_response = self.client.post(
            self.mark_read_url,
            data=json.dumps(
                {
                    "conversation_id": self.conversation.id,
                    "last_message_id": latest_message.id,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(list_response.status_code, 403)
        self.assertEqual(read_response.status_code, 403)
        self.assertFalse(
            ConversationReadState.objects.filter(
                conversation=self.conversation,
                user=self.assistant_user,
            ).exists()
        )

    def test_get_or_create_patient_conversation_does_not_move_existing_conversation_on_read(self):
        """普通获取患者会话不能把历史会话从旧工作室迁到新工作室。"""
        new_studio = DoctorStudio.objects.create(
            name="新工作室4",
            code="TCL_NEW4",
            owner_doctor=self.director_profile,
        )

        conversation = self.service.get_or_create_patient_conversation(
            patient=self.patient_profile,
            studio=new_studio,
            operator=self.assistant_user,
        )

        self.assertEqual(conversation.id, self.conversation.id)
        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.studio_id, self.studio.id)

    def test_get_or_create_internal_conversation_does_not_move_existing_conversation_on_read(self):
        """普通获取内部会话不能把历史会话从旧工作室迁到新工作室。"""
        internal_conversation = self.service.get_or_create_internal_conversation(
            patient=self.patient_profile,
            studio=self.studio,
            operator=self.assistant_user,
        )
        new_studio = DoctorStudio.objects.create(
            name="新工作室5",
            code="TCL_NEW5",
            owner_doctor=self.director_profile,
        )

        conversation = self.service.get_or_create_internal_conversation(
            patient=self.patient_profile,
            studio=new_studio,
            operator=self.assistant_user,
        )

        self.assertEqual(conversation.id, internal_conversation.id)
        internal_conversation.refresh_from_db()
        self.assertEqual(internal_conversation.studio_id, self.studio.id)

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

    def test_disabled_assistant_cannot_send_text_message_to_patient_conversation(self):
        self.assistant_profile.patient_chat_permission = (
            choices.AssistantPatientChatPermission.DISABLED
        )
        self.assistant_profile.save(update_fields=["patient_chat_permission"])

        self.client.force_login(self.assistant_user)
        before_count = Message.objects.filter(conversation=self.conversation).count()

        response = self.client.post(
            self.send_text_url,
            data=json.dumps({"conversation_id": self.conversation.id, "content": "禁发测试"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertEqual(payload["status"], "error")
        self.assertIn("该助理无权在患者会话发言", payload["message"])
        self.assertEqual(Message.objects.filter(conversation=self.conversation).count(), before_count)

    def test_disabled_assistant_cannot_upload_image_to_patient_conversation(self):
        self.assistant_profile.patient_chat_permission = (
            choices.AssistantPatientChatPermission.DISABLED
        )
        self.assistant_profile.save(update_fields=["patient_chat_permission"])
        image_file = SimpleUploadedFile(
            "patient.png",
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
            content_type="image/png",
        )

        self.client.force_login(self.assistant_user)
        before_count = Message.objects.filter(conversation=self.conversation).count()
        response = self.client.post(
            self.upload_image_url,
            data={"conversation_id": self.conversation.id, "image": image_file},
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertEqual(payload["status"], "error")
        self.assertIn("该助理无权在患者会话发言", payload["message"])
        self.assertEqual(Message.objects.filter(conversation=self.conversation).count(), before_count)

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

    def test_director_can_send_text_message_to_internal_conversation(self):
        internal_conversation = self.service.get_or_create_internal_conversation(
            patient=self.patient_profile,
            studio=self.studio,
            operator=self.director_user,
        )

        self.client.force_login(self.director_user)
        before_count = Message.objects.filter(conversation=internal_conversation).count()
        response = self.client.post(
            self.send_text_url,
            data=json.dumps({"conversation_id": internal_conversation.id, "content": "主任内部沟通"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "success")
        self.assertEqual(
            Message.objects.filter(conversation=internal_conversation).count(),
            before_count + 1,
        )
        last_message = Message.objects.filter(conversation=internal_conversation).order_by("-id").first()
        self.assertIsNotNone(last_message)
        self.assertEqual(last_message.sender_id, self.director_user.id)
        self.assertEqual(last_message.text_content, "主任内部沟通")

    def test_assistant_can_send_text_message_to_internal_conversation(self):
        internal_conversation = self.service.get_or_create_internal_conversation(
            patient=self.patient_profile,
            studio=self.studio,
            operator=self.assistant_user,
        )

        self.client.force_login(self.assistant_user)
        response = self.client.post(
            self.send_text_url,
            data=json.dumps({"conversation_id": internal_conversation.id, "content": "助理内部沟通"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "success")
        last_message = Message.objects.filter(conversation=internal_conversation).order_by("-id").first()
        self.assertIsNotNone(last_message)
        self.assertEqual(last_message.sender_id, self.assistant_user.id)
        self.assertEqual(last_message.text_content, "助理内部沟通")

    def test_disabled_assistant_can_send_text_message_to_internal_conversation(self):
        self.assistant_profile.patient_chat_permission = (
            choices.AssistantPatientChatPermission.DISABLED
        )
        self.assistant_profile.save(update_fields=["patient_chat_permission"])
        internal_conversation = self.service.get_or_create_internal_conversation(
            patient=self.patient_profile,
            studio=self.studio,
            operator=self.assistant_user,
        )

        self.client.force_login(self.assistant_user)
        response = self.client.post(
            self.send_text_url,
            data=json.dumps({"conversation_id": internal_conversation.id, "content": "禁患者聊但内部可发"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "success")
        last_message = Message.objects.filter(conversation=internal_conversation).order_by("-id").first()
        self.assertIsNotNone(last_message)
        self.assertEqual(last_message.sender_id, self.assistant_user.id)
        self.assertEqual(last_message.text_content, "禁患者聊但内部可发")

    def test_assistant_can_upload_image_to_internal_conversation(self):
        internal_conversation = self.service.get_or_create_internal_conversation(
            patient=self.patient_profile,
            studio=self.studio,
            operator=self.assistant_user,
        )
        image_file = SimpleUploadedFile(
            "internal.png",
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
            content_type="image/png",
        )

        self.client.force_login(self.assistant_user)
        response = self.client.post(
            self.upload_image_url,
            data={"conversation_id": internal_conversation.id, "image": image_file},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "success")
        last_message = Message.objects.filter(conversation=internal_conversation).order_by("-id").first()
        self.assertIsNotNone(last_message)
        self.assertEqual(last_message.sender_id, self.assistant_user.id)
        self.assertEqual(last_message.content_type, MessageContentType.IMAGE)
        self.assertTrue(bool(last_message.image))

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
