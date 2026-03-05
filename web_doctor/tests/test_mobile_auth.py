
from datetime import timedelta

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from chat.models import Conversation, Message
from chat.models.choices import ConversationType, MessageContentType
from patient_alerts.models import AlertEventType, AlertLevel, AlertStatus, PatientAlert
from users.models import (
    AssistantProfile,
    CustomUser,
    DoctorAssistantMap,
    DoctorProfile,
    DoctorStudio,
    PatientProfile,
    SalesProfile,
)
from users import choices
from users.services.auth import AuthService

class MobileAuthTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.login_url = reverse("web_doctor:login")
        self.mobile_home_url = reverse("web_doctor:mobile_home")
        self.doctor_workspace_url = reverse("web_doctor:doctor_workspace")
        
        # Create a doctor user
        self.password = "password123"
        self.doctor = CustomUser.objects.create_user(
            username="doctor_test",
            phone="13800000001",
            password=self.password,
            user_type=choices.UserType.DOCTOR,
            wx_nickname="昵称医生"
        )
        self.doctor_profile = DoctorProfile.objects.create(
            user=self.doctor,
            name="真实医生",
            title="主任医师",
            hospital="测试医院",
            department="测试科室"
        )
        self.studio = DoctorStudio.objects.create(
            name="真实工作室",
            code="STUDIO_TEST_001",
            owner_doctor=self.doctor_profile,
        )
        self.doctor_profile.studio = self.studio
        self.doctor_profile.save(update_fields=["studio"])

        # Create an assistant user
        self.assistant = CustomUser.objects.create_user(
            username="assistant_test",
            phone="13800000003",
            password=self.password,
            user_type=choices.UserType.ASSISTANT,
        )
        self.assistant_profile = AssistantProfile.objects.create(
            user=self.assistant,
            name="医助A",
            status=choices.AssistantStatus.ACTIVE,
        )
        DoctorAssistantMap.objects.create(
            doctor=self.doctor_profile,
            assistant=self.assistant_profile,
        )
        
        # Create a sales user
        self.sales = CustomUser.objects.create_user(
            username="sales_test",
            phone="13800000002",
            password=self.password,
            user_type=choices.UserType.SALES
        )
        SalesProfile.objects.create(
            user=self.sales,
            name="销售A"
        )

    def test_login_page_renders(self):
        """测试登录页面能否正常渲染"""
        response = self.client.get(self.login_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "login.html")

    def test_pc_login_redirects_to_workspace(self):
        """测试PC端医生登录跳转到工作台"""
        response = self.client.post(
            self.login_url,
            {"phone": self.doctor.phone, "password": self.password},
            HTTP_USER_AGENT="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        )
        self.assertRedirects(response, self.doctor_workspace_url)

    def test_mobile_login_redirects_to_mobile_home(self):
        """测试移动端医生登录跳转到移动端首页"""
        response = self.client.post(
            self.login_url,
            {"phone": self.doctor.phone, "password": self.password},
            HTTP_USER_AGENT="Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1"
        )
        self.assertRedirects(response, self.mobile_home_url)

    def test_mobile_login_android_redirects_to_mobile_home(self):
        """测试Android设备医生登录跳转到移动端首页"""
        response = self.client.post(
            self.login_url,
            {"phone": self.doctor.phone, "password": self.password},
            HTTP_USER_AGENT="Mozilla/5.0 (Linux; Android 10; SM-G975F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/83.0.4103.106 Mobile Safari/537.36"
        )
        self.assertRedirects(response, self.mobile_home_url)

    def test_assistant_mobile_login_redirects_to_mobile_home(self):
        """测试移动端医助登录跳转到移动端首页"""
        response = self.client.post(
            self.login_url,
            {"phone": self.assistant.phone, "password": self.password},
            HTTP_USER_AGENT="Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1"
        )
        self.assertRedirects(response, self.mobile_home_url)

    def test_assistant_pc_login_redirects_to_workspace(self):
        """测试PC端医助登录跳转到工作台"""
        response = self.client.post(
            self.login_url,
            {"phone": self.assistant.phone, "password": self.password},
            HTTP_USER_AGENT="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        )
        self.assertRedirects(response, self.doctor_workspace_url)

    def test_sales_login_redirects_to_dashboard_regardless_of_device(self):
        """测试销售登录始终跳转到销售看板，不受设备影响"""
        # PC
        response = self.client.post(
            self.login_url,
            {"phone": self.sales.phone, "password": self.password},
            HTTP_USER_AGENT="Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        )
        self.assertRedirects(response, reverse("web_sales:sales_dashboard"))
        
        self.client.logout()
        
        # Mobile
        response = self.client.post(
            self.login_url,
            {"phone": self.sales.phone, "password": self.password},
            HTTP_USER_AGENT="Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X)"
        )
        self.assertRedirects(response, reverse("web_sales:sales_dashboard"))

    def test_mobile_home_view_renders_correctly(self):
        """测试移动端首页视图渲染及真实数据包含"""
        patient_user_1 = CustomUser.objects.create_user(
            username="patient_user_1",
            wx_openid="openid_patient_1",
            user_type=choices.UserType.PATIENT,
        )
        patient_1 = PatientProfile.objects.create(
            user=patient_user_1,
            phone="13911110001",
            name="患者甲",
            doctor=self.doctor_profile,
            is_active=True,
            last_active_at=timezone.now(),
        )
        PatientProfile.objects.create(
            phone="13911110002",
            name="患者乙",
            doctor=self.doctor_profile,
            is_active=True,
            last_active_at=timezone.now() - timedelta(days=1),
        )

        PatientAlert.objects.create(
            patient=patient_1,
            doctor=self.doctor_profile,
            event_type=AlertEventType.DATA,
            event_level=AlertLevel.MILD,
            event_title="体征异常",
            event_time=timezone.now(),
            status=AlertStatus.PENDING,
        )

        conversation = Conversation.objects.create(
            patient=patient_1,
            studio=self.studio,
            type=ConversationType.PATIENT_STUDIO,
            created_by=self.doctor,
            last_message_at=timezone.now(),
        )
        Message.objects.create(
            conversation=conversation,
            sender=patient_user_1,
            sender_display_name_snapshot=patient_1.name,
            studio_name_snapshot=self.studio.name,
            content_type=MessageContentType.TEXT,
            text_content="已经连续3天发烧......",
        )

        self.client.force_login(self.doctor)
        response = self.client.get(self.mobile_home_url)
        
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "web_doctor/mobile/index.html")
        
        ctx = response.context
        self.assertEqual(ctx["doctor"]["name"], "真实医生")
        self.assertEqual(ctx["doctor"]["hospital"], "测试医院")
        self.assertEqual(ctx["doctor"]["department"], "测试科室")
        self.assertEqual(ctx["doctor"]["phone"], "13800000001")
        self.assertEqual(ctx["doctor"]["studio_name"], "真实工作室")

        self.assertEqual(ctx["stats"]["managed_patients"], 2)
        self.assertEqual(ctx["stats"]["today_active"], 1)
        self.assertEqual(ctx["stats"]["alerts_count"], 1)
        self.assertEqual(ctx["stats"]["consultations_count"], 1)

        self.assertEqual(ctx["alerts"][0]["patient_name"], "患者甲")
        self.assertEqual(ctx["alerts"][0]["type"], "体征异常")
        self.assertEqual(ctx["consultations"][0]["patient_name"], "患者甲")
        self.assertIn("已经连续3天发烧", ctx["consultations"][0]["content"])
