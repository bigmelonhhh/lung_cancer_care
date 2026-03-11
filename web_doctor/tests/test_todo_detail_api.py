from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from patient_alerts.models import AlertEventType, AlertLevel, AlertStatus, PatientAlert
from patient_alerts.services.patient_alert import PatientAlertService
from users import choices
from users.models import (
    AssistantProfile,
    CustomUser,
    DoctorAssistantMap,
    DoctorProfile,
    PatientProfile,
)


class TodoDetailApiTests(TestCase):
    def setUp(self):
        self.password = "password123"

        self.doctor_user = CustomUser.objects.create_user(
            username="doctor_todo_detail",
            phone="13900000001",
            password=self.password,
            user_type=choices.UserType.DOCTOR,
        )
        self.doctor_profile = DoctorProfile.objects.create(
            user=self.doctor_user,
            name="主任甲",
            hospital="测试医院",
        )

        self.assistant_user = CustomUser.objects.create_user(
            username="assistant_todo_detail",
            phone="13900000002",
            password=self.password,
            user_type=choices.UserType.ASSISTANT,
        )
        self.assistant_profile = AssistantProfile.objects.create(
            user=self.assistant_user,
            name="助理甲",
            status=choices.AssistantStatus.ACTIVE,
        )
        DoctorAssistantMap.objects.create(
            doctor=self.doctor_profile,
            assistant=self.assistant_profile,
        )

        patient_user = CustomUser.objects.create_user(
            username="patient_todo_detail",
            phone="13900000003",
            user_type=choices.UserType.PATIENT,
            wx_openid="wx_todo_detail",
        )
        self.patient = PatientProfile.objects.create(
            user=patient_user,
            doctor=self.doctor_profile,
            name="患者甲",
            phone="13900000003",
            is_active=True,
        )

        self.alert = PatientAlert.objects.create(
            patient=self.patient,
            doctor=self.doctor_profile,
            event_type=AlertEventType.DATA,
            event_level=AlertLevel.MODERATE,
            event_title="血氧预警",
            event_content="血氧下降",
            event_time=timezone.now(),
            status=AlertStatus.PENDING,
        )

        self.detail_url = reverse("web_doctor:doctor_todo_detail")

    def test_detail_returns_history_in_latest_first_order(self):
        first_time = timezone.now() - timedelta(hours=1)
        second_time = timezone.now()

        PatientAlertService.update_status(
            alert_id=self.alert.id,
            status=AlertStatus.PENDING,
            handler_id=self.assistant_user.id,
            handle_content="首次电话随访，继续观察",
            handled_at=first_time,
        )
        PatientAlertService.update_status(
            alert_id=self.alert.id,
            status=AlertStatus.COMPLETED,
            handler_id=self.doctor_user.id,
            handle_content="二次复查后确认完成",
            handled_at=second_time,
        )

        self.client.force_login(self.assistant_user)
        response = self.client.get(self.detail_url, {"id": self.alert.id})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        history = payload["data"]["history"]
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["status_code"], "completed")
        self.assertEqual(history[0]["handle_content"], "二次复查后确认完成")
        self.assertEqual(history[1]["status_code"], "pending")
        self.assertEqual(history[1]["handle_content"], "首次电话随访，继续观察")

    def test_detail_rejects_alert_outside_access_scope(self):
        other_doctor_user = CustomUser.objects.create_user(
            username="doctor_todo_detail_other",
            phone="13900000004",
            password=self.password,
            user_type=choices.UserType.DOCTOR,
        )
        other_doctor_profile = DoctorProfile.objects.create(
            user=other_doctor_user,
            name="主任乙",
            hospital="测试医院",
        )
        other_patient_user = CustomUser.objects.create_user(
            username="patient_todo_detail_other",
            phone="13900000005",
            user_type=choices.UserType.PATIENT,
            wx_openid="wx_todo_detail_other",
        )
        other_patient = PatientProfile.objects.create(
            user=other_patient_user,
            doctor=other_doctor_profile,
            name="患者乙",
            phone="13900000005",
            is_active=True,
        )
        other_alert = PatientAlert.objects.create(
            patient=other_patient,
            doctor=other_doctor_profile,
            event_type=AlertEventType.DATA,
            event_level=AlertLevel.MILD,
            event_title="其他医生待办",
            status=AlertStatus.PENDING,
        )

        self.client.force_login(self.doctor_user)
        response = self.client.get(self.detail_url, {"id": other_alert.id})

        self.assertEqual(response.status_code, 404)
        payload = response.json()
        self.assertFalse(payload["success"])

    def test_detail_returns_empty_history_for_never_handled_alert(self):
        self.client.force_login(self.doctor_user)
        response = self.client.get(self.detail_url, {"id": self.alert.id})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["data"]["history"], [])

    def test_detail_fallbacks_when_history_empty_but_legacy_fields_exist(self):
        handled_at = timezone.now()
        self.alert.status = AlertStatus.ESCALATED
        self.alert.handler = self.assistant_user
        self.alert.handle_content = "旧数据仅写入了主字段"
        self.alert.handle_time = handled_at
        self.alert.handle_meta = {}
        self.alert.save(
            update_fields=[
                "status",
                "handler",
                "handle_content",
                "handle_time",
                "handle_meta",
            ]
        )

        self.client.force_login(self.doctor_user)
        response = self.client.get(self.detail_url, {"id": self.alert.id})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        history = payload["data"]["history"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["status_code"], "escalate")
        self.assertEqual(history[0]["status_display"], "升级主任")
        self.assertEqual(history[0]["handle_content"], "旧数据仅写入了主字段")
        self.assertEqual(history[0]["handler_name"], "助理甲")

