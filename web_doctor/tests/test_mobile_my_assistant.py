from datetime import timedelta

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from users import choices
from users.models import (
    AssistantProfile,
    CustomUser,
    DoctorAssistantMap,
    DoctorProfile,
    DoctorStudio,
    PatientProfile,
)


class MobileMyAssistantTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.my_assistant_url = reverse("web_doctor:mobile_my_assistant")
        self.related_doctors_url = reverse("web_doctor:mobile_related_doctors")

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
        self.assertContains(response, "暂无助理数据")

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
            department="非主任科室",
            studio=self.studio,
        )

        self.client.force_login(other_doctor)
        response = self.client.get(self.my_assistant_url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "web_doctor/mobile/my_assistant.html")
        self.assertEqual(list(response.context["assistants"]), [])
        self.assertContains(response, "暂无助理数据")

    def test_sales_user_forbidden(self):
        self.client.force_login(self.sales_user)
        response = self.client.get(self.my_assistant_url)
        self.assertEqual(response.status_code, 403)

    def test_assistant_user_sees_related_chief_doctors(self):
        self.client.force_login(self.assistant_user)
        response = self.client.get(self.related_doctors_url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "web_doctor/mobile/related_doctors.html")
        self.assertContains(response, "张主任")

    def test_assistant_related_doctors_filters_non_chief_doctors(self):
        non_chief_user = CustomUser.objects.create_user(
            username="doctor_related_non_chief",
            phone="13800001008",
            password=self.password,
            user_type=choices.UserType.DOCTOR,
        )
        non_chief_profile = DoctorProfile.objects.create(
            user=non_chief_user,
            name="普通医生",
            title="主治医师",
            hospital="测试医院",
            department="测试科室",
            studio=self.studio,
        )
        DoctorAssistantMap.objects.create(
            doctor=non_chief_profile,
            assistant=self.assistant_profile,
        )

        self.client.force_login(self.assistant_user)
        response = self.client.get(self.related_doctors_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "张主任")
        self.assertNotContains(response, "普通医生")

    def test_assistant_related_doctors_shows_empty_when_no_chief(self):
        assistant_user = CustomUser.objects.create_user(
            username="assistant_related_only_non_chief",
            phone="13800001009",
            password=self.password,
            user_type=choices.UserType.ASSISTANT,
        )
        assistant_profile = AssistantProfile.objects.create(
            user=assistant_user,
            name="平台助理B",
            status=choices.AssistantStatus.ACTIVE,
        )
        non_chief_user = CustomUser.objects.create_user(
            username="doctor_related_only_non_chief",
            phone="13800001010",
            password=self.password,
            user_type=choices.UserType.DOCTOR,
        )
        non_chief_profile = DoctorProfile.objects.create(
            user=non_chief_user,
            name="非主任医生",
            title="主治医师",
            hospital="测试医院",
            department="测试科室",
            studio=self.studio,
        )
        DoctorAssistantMap.objects.create(
            doctor=non_chief_profile,
            assistant=assistant_profile,
        )

        self.client.force_login(assistant_user)
        response = self.client.get(self.related_doctors_url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "web_doctor/mobile/related_doctors.html")
        self.assertEqual(list(response.context["related_doctors"]), [])
        self.assertContains(response, "暂无关联医生")

    def test_mobile_related_doctors_permissions(self):
        self.client.force_login(self.doctor)
        doctor_response = self.client.get(self.related_doctors_url)
        self.assertEqual(doctor_response.status_code, 403)

        self.client.force_login(self.sales_user)
        sales_response = self.client.get(self.related_doctors_url)
        self.assertEqual(sales_response.status_code, 403)

    def test_mobile_home_has_my_assistant_entry(self):
        self.client.force_login(self.doctor)
        response = self.client.get(reverse("web_doctor:mobile_home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("web_doctor:mobile_my_assistant"))
        self.assertTrue(response.context["show_my_assistant"])
        self.assertFalse(response.context["show_related_doctors"])
        self.assertTrue(response.context["show_department"])
        self.assertTrue(response.context["show_hospital"])
        self.assertNotContains(response, reverse("web_doctor:mobile_related_doctors"))
        self.assertContains(response, "测试医院")

    def test_mobile_home_assistant_identity_and_visibility(self):
        self.client.force_login(self.assistant_user)
        response = self.client.get(reverse("web_doctor:mobile_home"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["doctor"]["name"], "平台助理A")
        self.assertEqual(response.context["doctor"]["title"], "平台助理")
        self.assertFalse(response.context["show_my_assistant"])
        self.assertTrue(response.context["show_related_doctors"])
        self.assertFalse(response.context["show_department"])
        self.assertFalse(response.context["show_hospital"])
        self.assertNotContains(response, reverse("web_doctor:mobile_my_assistant"))
        self.assertContains(response, reverse("web_doctor:mobile_related_doctors"))
        self.assertNotContains(response, "测试科室")
        self.assertNotContains(response, "测试医院")

    def test_mobile_home_non_chief_hides_department_and_my_assistant(self):
        other_doctor = CustomUser.objects.create_user(
            username="doctor_my_assistant_other_home",
            phone="13800001005",
            password=self.password,
            user_type=choices.UserType.DOCTOR,
        )
        DoctorProfile.objects.create(
            user=other_doctor,
            name="王医生",
            title="主治医师",
            hospital="测试医院",
            department="非主任科室",
            studio=self.studio,
        )

        self.client.force_login(other_doctor)
        response = self.client.get(reverse("web_doctor:mobile_home"))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["show_my_assistant"])
        self.assertFalse(response.context["show_related_doctors"])
        self.assertFalse(response.context["show_department"])
        self.assertFalse(response.context["show_hospital"])
        self.assertNotContains(response, reverse("web_doctor:mobile_my_assistant"))
        self.assertNotContains(response, reverse("web_doctor:mobile_related_doctors"))
        self.assertNotContains(response, "非主任科室")
        self.assertNotContains(response, "测试医院")

    def test_mobile_home_assistant_aggregates_multi_doctor_studios_and_stats(self):
        second_doctor = CustomUser.objects.create_user(
            username="doctor_my_assistant_second",
            phone="13800001006",
            password=self.password,
            user_type=choices.UserType.DOCTOR,
        )
        second_profile = DoctorProfile.objects.create(
            user=second_doctor,
            name="李主任",
            title="主任医师",
            hospital="第二医院",
            department="第二科室",
        )
        second_studio = DoctorStudio.objects.create(
            name="李主任工作室",
            code="STU_MYASST_002",
            owner_doctor=second_profile,
        )
        second_profile.studio = second_studio
        second_profile.save(update_fields=["studio"])

        DoctorAssistantMap.objects.create(
            doctor=second_profile,
            assistant=self.assistant_profile,
        )

        patient_user_1 = CustomUser.objects.create_user(
            username="patient_my_assistant_1",
            wx_openid="openid_my_assistant_1",
            user_type=choices.UserType.PATIENT,
        )
        PatientProfile.objects.create(
            user=patient_user_1,
            phone="13911111001",
            name="患者甲",
            doctor=self.doctor_profile,
            is_active=True,
            last_active_at=timezone.now(),
        )
        patient_user_2 = CustomUser.objects.create_user(
            username="patient_my_assistant_2",
            wx_openid="openid_my_assistant_2",
            user_type=choices.UserType.PATIENT,
        )
        PatientProfile.objects.create(
            user=patient_user_2,
            phone="13911111002",
            name="患者乙",
            doctor=second_profile,
            is_active=True,
            last_active_at=timezone.now(),
        )
        patient_user_3 = CustomUser.objects.create_user(
            username="patient_my_assistant_3",
            wx_openid="openid_my_assistant_3",
            user_type=choices.UserType.PATIENT,
        )
        PatientProfile.objects.create(
            user=patient_user_3,
            phone="13911111003",
            name="患者丙",
            doctor=second_profile,
            is_active=True,
            last_active_at=timezone.now() - timedelta(days=1),
        )
        PatientProfile.objects.create(
            phone="13911111004",
            name="患者丁",
            doctor=self.doctor_profile,
            is_active=False,
            last_active_at=timezone.now(),
        )

        self.client.force_login(self.assistant_user)
        response = self.client.get(reverse("web_doctor:mobile_home"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["doctor"]["name"], "平台助理A")
        self.assertEqual(response.context["doctor"]["title"], "平台助理")
        self.assertFalse(response.context["show_department"])
        self.assertFalse(response.context["show_hospital"])
        self.assertFalse(response.context["show_my_assistant"])
        self.assertTrue(response.context["show_related_doctors"])
        self.assertContains(response, reverse("web_doctor:mobile_related_doctors"))

        studio_names = set(response.context["doctor"]["studio_name"].split("、"))
        self.assertEqual(studio_names, {"张主任工作室", "李主任工作室"})
        self.assertEqual(response.context["stats"]["managed_patients"], 3)
        self.assertEqual(response.context["stats"]["today_active"], 3)

    def test_mobile_home_assistant_without_linked_doctor_keeps_404(self):
        no_link_user = CustomUser.objects.create_user(
            username="assistant_my_assistant_no_link",
            phone="13800001007",
            password=self.password,
            user_type=choices.UserType.ASSISTANT,
        )
        AssistantProfile.objects.create(
            user=no_link_user,
            name="平台助理B",
            status=choices.AssistantStatus.ACTIVE,
        )

        self.client.force_login(no_link_user)
        response = self.client.get(reverse("web_doctor:mobile_home"))

        self.assertEqual(response.status_code, 404)
        self.assertContains(
            response,
            "未找到医生档案信息，请联系管理员完善医生资料。",
            status_code=404,
        )
        self.assertTrue(response.context["show_related_doctors"])
        self.assertContains(
            response,
            reverse("web_doctor:mobile_related_doctors"),
            status_code=404,
        )
