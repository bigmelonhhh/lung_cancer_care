from django.test import Client, TestCase
from django.urls import reverse

from users import choices
from users.models import (
    AssistantProfile,
    CustomUser,
    DoctorAssistantMap,
    DoctorProfile,
    DoctorStudio,
)


class MobileMyAssistantTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.my_assistant_url = reverse("web_doctor:mobile_my_assistant")

        self.password = "password123"
        self.doctor = CustomUser.objects.create_user(
            username="doctor_my_assistant",
            phone="13800001001",
            password=self.password,
            user_type=choices.UserType.DOCTOR,
        )
        self.doctor_profile = DoctorProfile.objects.create(
            user=self.doctor,
            name="张主任",
            title="主任医师",
            hospital="测试医院",
            department="测试科室",
        )
        self.studio = DoctorStudio.objects.create(
            name="张主任工作室",
            code="STU_MYASST_001",
            owner_doctor=self.doctor_profile,
        )
        self.doctor_profile.studio = self.studio
        self.doctor_profile.save(update_fields=["studio"])

        self.assistant_user = CustomUser.objects.create_user(
            username="assistant_my_assistant",
            phone="13800001002",
            password=self.password,
            user_type=choices.UserType.ASSISTANT,
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

        self.sales_user = CustomUser.objects.create_user(
            username="sales_my_assistant",
            phone="13800001003",
            password=self.password,
            user_type=choices.UserType.SALES,
        )

    def test_assistant_user_sees_empty_list(self):
        self.client.force_login(self.assistant_user)
        response = self.client.get(self.my_assistant_url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "web_doctor/mobile/my_assistant.html")
        self.assertEqual(list(response.context["assistants"]), [])
        self.assertContains(response, "暂无数据")

    def test_chief_doctor_sees_assistants(self):
        self.client.force_login(self.doctor)
        response = self.client.get(self.my_assistant_url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "web_doctor/mobile/my_assistant.html")
        self.assertContains(response, "平台助理A")
        self.assertContains(response, "医生助理")

    def test_non_chief_doctor_sees_empty_list(self):
        other_doctor = CustomUser.objects.create_user(
            username="doctor_my_assistant_other",
            phone="13800001004",
            password=self.password,
            user_type=choices.UserType.DOCTOR,
        )
        other_profile = DoctorProfile.objects.create(
            user=other_doctor,
            name="李医生",
            title="主治医师",
            hospital="测试医院",
            department="测试科室",
            studio=self.studio,
        )

        self.client.force_login(other_doctor)
        response = self.client.get(self.my_assistant_url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "web_doctor/mobile/my_assistant.html")
        self.assertEqual(list(response.context["assistants"]), [])
        self.assertContains(response, "暂无数据")

    def test_sales_user_forbidden(self):
        self.client.force_login(self.sales_user)
        response = self.client.get(self.my_assistant_url)
        self.assertEqual(response.status_code, 403)

    def test_mobile_home_has_my_assistant_entry(self):
        self.client.force_login(self.doctor)
        response = self.client.get(reverse("web_doctor:mobile_home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("web_doctor:mobile_my_assistant"))
