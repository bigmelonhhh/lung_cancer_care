from datetime import timedelta
from unittest.mock import patch

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from chat.models import Conversation, Message
from chat.models.choices import ConversationType, MessageContentType
from patient_alerts.models import AlertEventType, AlertLevel, AlertStatus, PatientAlert
from users import choices
from users.models import CustomUser, DoctorProfile, DoctorStudio, PatientProfile


class MobileHomeDefaultLimitTests(TestCase):
    """移动端首页默认仅展示 1 条列表数据相关测试"""

    def setUp(self):
        self.client = Client()
        self.mobile_home_url = reverse("web_doctor:mobile_home")

        self.password = "password123"
        self.doctor = CustomUser.objects.create_user(
            username="doctor_limit_test",
            phone="13800000101",
            password=self.password,
            user_type=choices.UserType.DOCTOR,
            wx_nickname="昵称医生",
        )
        self.doctor_profile = DoctorProfile.objects.create(
            user=self.doctor,
            name="真实医生",
            title="主任医师",
            hospital="测试医院",
            department="测试科室",
        )
        self.studio = DoctorStudio.objects.create(
            name="真实工作室",
            code="STUDIO_LIMIT_001",
            owner_doctor=self.doctor_profile,
        )
        self.doctor_profile.studio = self.studio
        self.doctor_profile.save(update_fields=["studio"])

        patient_user = CustomUser.objects.create_user(
            username="patient_limit_1",
            wx_openid="openid_patient_limit_1",
            user_type=choices.UserType.PATIENT,
        )
        self.patient = PatientProfile.objects.create(
            user=patient_user,
            phone="13911110101",
            name="患者甲",
            doctor=self.doctor_profile,
            is_active=True,
            last_active_at=timezone.now(),
        )

    def test_mobile_home_alerts_default_returns_one_when_multiple_exist(self):
        """待办数量>=1 时默认仅返回 1 条"""
        PatientAlert.objects.create(
            patient=self.patient,
            doctor=self.doctor_profile,
            event_type=AlertEventType.DATA,
            event_level=AlertLevel.MILD,
            event_title="体征异常A",
            event_time=timezone.now(),
            status=AlertStatus.PENDING,
        )
        PatientAlert.objects.create(
            patient=self.patient,
            doctor=self.doctor_profile,
            event_type=AlertEventType.DATA,
            event_level=AlertLevel.MODERATE,
            event_title="体征异常B",
            event_time=timezone.now() - timedelta(minutes=1),
            status=AlertStatus.PENDING,
        )

        self.client.force_login(self.doctor)
        response = self.client.get(self.mobile_home_url)

        self.assertEqual(response.status_code, 200)
        ctx = response.context
        self.assertEqual(ctx["stats"]["alerts_count"], 2)
        self.assertEqual(len(ctx["alerts"]), 1)

    def test_mobile_home_alerts_returns_empty_list_when_none_exist(self):
        """待办数量为 0 时返回空列表且不报错"""
        self.client.force_login(self.doctor)
        response = self.client.get(self.mobile_home_url)

        self.assertEqual(response.status_code, 200)
        ctx = response.context
        self.assertEqual(ctx["stats"]["alerts_count"], 0)
        self.assertEqual(ctx["alerts"], [])

    def test_mobile_home_consultations_default_returns_one_when_multiple_unread_exist(self):
        """咨询未读数量>=1 时默认仅返回 1 条"""
        patient_user_2 = CustomUser.objects.create_user(
            username="patient_limit_2",
            wx_openid="openid_patient_limit_2",
            user_type=choices.UserType.PATIENT,
        )
        patient_2 = PatientProfile.objects.create(
            user=patient_user_2,
            phone="13911110102",
            name="患者乙",
            doctor=self.doctor_profile,
            is_active=True,
            last_active_at=timezone.now(),
        )

        conversation_1 = Conversation.objects.create(
            patient=self.patient,
            studio=self.studio,
            type=ConversationType.PATIENT_STUDIO,
            created_by=self.doctor,
            last_message_at=timezone.now(),
        )
        Message.objects.create(
            conversation=conversation_1,
            sender=self.patient.user,
            sender_display_name_snapshot=self.patient.name,
            studio_name_snapshot=self.studio.name,
            content_type=MessageContentType.TEXT,
            text_content="咨询消息1",
        )

        conversation_2 = Conversation.objects.create(
            patient=patient_2,
            studio=self.studio,
            type=ConversationType.PATIENT_STUDIO,
            created_by=self.doctor,
            last_message_at=timezone.now() - timedelta(minutes=3),
        )
        Message.objects.create(
            conversation=conversation_2,
            sender=patient_user_2,
            sender_display_name_snapshot=patient_2.name,
            studio_name_snapshot=self.studio.name,
            content_type=MessageContentType.TEXT,
            text_content="咨询消息2",
        )

        self.client.force_login(self.doctor)
        response = self.client.get(self.mobile_home_url)

        self.assertEqual(response.status_code, 200)
        ctx = response.context
        self.assertEqual(ctx["stats"]["consultations_count"], 2)
        self.assertEqual(len(ctx["consultations"]), 1)

    def test_mobile_home_consultations_returns_empty_list_when_none_exist(self):
        """咨询数量为 0 时返回空列表且不报错"""
        self.client.force_login(self.doctor)
        response = self.client.get(self.mobile_home_url)

        self.assertEqual(response.status_code, 200)
        ctx = response.context
        self.assertEqual(ctx["stats"]["consultations_count"], 0)
        self.assertEqual(ctx["consultations"], [])

    def test_mobile_home_consultations_page_param_supports_load_more(self):
        """存在分页参数时，咨询列表可按 page/size 取下一页"""
        summaries = [
            {
                "conversation_id": 1001,
                "patient_name": "患者甲",
                "unread_count": 1,
                "last_message_type": MessageContentType.TEXT,
                "last_message_text": "消息A",
                "last_message_at": timezone.now(),
            },
            {
                "conversation_id": 1002,
                "patient_name": "患者乙",
                "unread_count": 1,
                "last_message_type": MessageContentType.TEXT,
                "last_message_text": "消息B",
                "last_message_at": timezone.now() - timedelta(minutes=1),
            },
        ]

        self.client.force_login(self.doctor)
        with patch(
            "web_doctor.views.mobile.views.ChatService.list_patient_conversation_summaries",
            return_value=summaries,
        ):
            response_page_1 = self.client.get(self.mobile_home_url, {"consultations_page": 1, "consultations_size": 1})
            response_page_2 = self.client.get(self.mobile_home_url, {"consultations_page": 2, "consultations_size": 1})

        self.assertEqual(response_page_1.status_code, 200)
        self.assertEqual(response_page_2.status_code, 200)
        self.assertEqual(len(response_page_1.context["consultations"]), 1)
        self.assertEqual(len(response_page_2.context["consultations"]), 1)
        self.assertNotEqual(
            response_page_1.context["consultations"][0]["id"],
            response_page_2.context["consultations"][0]["id"],
        )

    def test_mobile_home_alerts_and_consultations_sections_link_to_patient_list(self):
        """首页异常警报与咨询模块点击跳转到患者列表页"""
        self.client.force_login(self.doctor)
        response = self.client.get(self.mobile_home_url)

        self.assertEqual(response.status_code, 200)
        patient_list_url = reverse("web_doctor:mobile_patient_list")
        self.assertContains(response, f'href="{patient_list_url}"')
        self.assertContains(response, 'aria-label="查看患者列表（异常警报）"')
        self.assertContains(response, 'aria-label="查看患者列表（咨询）"')
