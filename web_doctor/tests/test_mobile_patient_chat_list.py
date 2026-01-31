from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from chat.services.chat import ChatService
from users import choices
from users.models import DoctorProfile, DoctorStudio, PatientProfile

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

    def test_page_renders_html(self):
        """测试页面可正常渲染并包含标题信息。"""
        self.client.force_login(self.doctor_user)
        url = reverse(
            "web_doctor:mobile_patient_chat_list", kwargs={"patient_id": self.patient_profile.id}
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "web_doctor/mobile/patient_chat_list.html")
        self.assertContains(response, self.patient_profile.name)

    def test_api_paginates_latest_then_older(self):
        """测试接口按时间升序返回最新20条，并支持游标分页加载更早记录。"""
        self.client.force_login(self.doctor_user)
        url = reverse(
            "web_doctor:mobile_patient_chat_list", kwargs={"patient_id": self.patient_profile.id}
        )
        response = self.client.get(f"{url}?format=json")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("messages", payload)
        self.assertEqual(len(payload["messages"]), 20)
        ids = [m["id"] for m in payload["messages"]]
        self.assertEqual(ids, sorted(ids))
        self.assertTrue(payload["has_next"])
        self.assertTrue(payload["next_cursor"])

        cursor = payload["next_cursor"]
        response2 = self.client.get(f"{url}?format=json&cursor={cursor}")
        self.assertEqual(response2.status_code, 200)
        payload2 = response2.json()
        self.assertEqual(len(payload2["messages"]), 5)
        ids2 = [m["id"] for m in payload2["messages"]]
        self.assertEqual(ids2, sorted(ids2))
        self.assertFalse(payload2["has_next"])
        self.assertFalse(payload2["next_cursor"])

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
        url = reverse(
            "web_doctor:mobile_patient_chat_list", kwargs={"patient_id": self.patient_profile.id}
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)
