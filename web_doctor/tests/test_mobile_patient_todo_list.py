import json
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from patient_alerts.models import AlertEventType, AlertLevel, AlertStatus, PatientAlert
from users import choices
from users.models import (
    AssistantProfile,
    CustomUser,
    DoctorAssistantMap,
    DoctorProfile,
    PatientProfile,
)


class MobilePatientTodoListTests(TestCase):
    def setUp(self):
        self.password = "password123"

        self.doctor_user = CustomUser.objects.create_user(
            username="doctor_mobile_todo",
            phone="13810000001",
            password=self.password,
            user_type=choices.UserType.DOCTOR,
        )
        self.doctor_profile = DoctorProfile.objects.create(
            user=self.doctor_user,
            name="张主任",
            title="主任医师",
            hospital="测试医院",
            department="肿瘤科",
        )

        self.assistant_user = CustomUser.objects.create_user(
            username="assistant_mobile_todo",
            phone="13810000002",
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

        patient_user_1 = CustomUser.objects.create_user(
            username="patient_mobile_todo_1",
            phone="13810000003",
            user_type=choices.UserType.PATIENT,
            wx_openid="wx_mobile_todo_1",
        )
        self.patient_1 = PatientProfile.objects.create(
            user=patient_user_1,
            doctor=self.doctor_profile,
            name="患者甲",
            phone="13820000001",
            is_active=True,
        )

        patient_user_2 = CustomUser.objects.create_user(
            username="patient_mobile_todo_2",
            phone="13810000004",
            user_type=choices.UserType.PATIENT,
            wx_openid="wx_mobile_todo_2",
        )
        self.patient_2 = PatientProfile.objects.create(
            user=patient_user_2,
            doctor=self.doctor_profile,
            name="患者乙",
            phone="13820000002",
            is_active=True,
        )

        self.pending_alert = PatientAlert.objects.create(
            patient=self.patient_1,
            doctor=self.doctor_profile,
            event_type=AlertEventType.DATA,
            event_level=AlertLevel.MILD,
            event_title="体温异常待处理",
            event_content="请尽快随访",
            event_time=timezone.now(),
            status=AlertStatus.PENDING,
        )
        self.completed_alert = PatientAlert.objects.create(
            patient=self.patient_1,
            doctor=self.doctor_profile,
            event_type=AlertEventType.BEHAVIOR,
            event_level=AlertLevel.MODERATE,
            event_title="用药完成记录",
            event_content="已完成复核",
            event_time=timezone.now() - timedelta(hours=1),
            status=AlertStatus.COMPLETED,
            handler=self.doctor_user,
            handle_time=timezone.now() - timedelta(minutes=30),
            handle_content="医生已处理",
        )
        self.other_patient_alert = PatientAlert.objects.create(
            patient=self.patient_2,
            doctor=self.doctor_profile,
            event_type=AlertEventType.DATA,
            event_level=AlertLevel.MILD,
            event_title="其他患者告警",
            event_content="不应出现在患者甲过滤结果",
            event_time=timezone.now() - timedelta(hours=2),
            status=AlertStatus.PENDING,
        )

        self.mobile_todo_url = reverse("web_doctor:mobile_patient_todo_list")
        self.update_status_url = reverse("web_doctor:doctor_todo_update_status")

    def test_assistant_sees_process_for_non_completed_and_view_for_completed(self):
        self.client.force_login(self.assistant_user)
        response = self.client.get(self.mobile_todo_url, {"patient_id": self.patient_1.id})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-test="todo-action-process"')
        self.assertContains(response, 'data-test="todo-action-view"')
        self.assertContains(response, "去处理")
        self.assertContains(response, "去查看")

    def test_doctor_sees_only_view_actions(self):
        self.client.force_login(self.doctor_user)
        response = self.client.get(self.mobile_todo_url, {"patient_id": self.patient_1.id})

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'data-test="todo-action-process"')
        self.assertContains(response, 'data-test="todo-action-view"')
        self.assertNotContains(response, "去处理")
        self.assertContains(response, "去查看")

    def test_htmx_partial_keeps_role_action_rules(self):
        self.client.force_login(self.assistant_user)
        response_assistant = self.client.get(
            self.mobile_todo_url,
            {"patient_id": self.patient_1.id, "page": 1, "pagesize": 1},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response_assistant.status_code, 200)
        self.assertContains(response_assistant, 'data-test="todo-action-process"')

        self.client.force_login(self.doctor_user)
        response_doctor = self.client.get(
            self.mobile_todo_url,
            {"patient_id": self.patient_1.id, "page": 1, "pagesize": 1},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response_doctor.status_code, 200)
        self.assertNotContains(response_doctor, 'data-test="todo-action-process"')
        self.assertContains(response_doctor, 'data-test="todo-action-view"')

    def test_assistant_can_update_todo_status_successfully(self):
        self.client.force_login(self.assistant_user)
        response = self.client.post(
            self.update_status_url,
            data=json.dumps(
                {
                    "id": self.pending_alert.id,
                    "status": "completed",
                    "handle_content": "助理已电话随访并完成处理",
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])

        self.pending_alert.refresh_from_db()
        self.assertEqual(self.pending_alert.status, AlertStatus.COMPLETED)
        self.assertEqual(self.pending_alert.handler_id, self.assistant_user.id)
        self.assertEqual(self.pending_alert.handle_content, "助理已电话随访并完成处理")
        self.assertIsNotNone(self.pending_alert.handle_time)

    def test_update_todo_status_rejects_invalid_status(self):
        self.client.force_login(self.assistant_user)
        response = self.client.post(
            self.update_status_url,
            data=json.dumps(
                {
                    "id": self.pending_alert.id,
                    "status": "invalid-status",
                    "handle_content": "无效状态",
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertFalse(payload["success"])
        self.assertIn("无效的状态值", payload["message"])

    def test_mobile_todo_list_filters_by_patient_id(self):
        self.client.force_login(self.doctor_user)
        response = self.client.get(self.mobile_todo_url, {"patient_id": self.patient_1.id})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "体温异常待处理")
        self.assertContains(response, "用药完成记录")
        self.assertNotContains(response, "其他患者告警")
