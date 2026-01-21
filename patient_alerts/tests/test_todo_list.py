from datetime import datetime, timedelta

from django.test import TestCase
from django.utils import timezone

from core.models import QuestionnaireCode
from health_data.models import MetricType
from patient_alerts.models import AlertEventType, AlertLevel, AlertStatus, PatientAlert
from patient_alerts.services.todo_list import TodoListService
from users import choices
from users.models import CustomUser, DoctorProfile, PatientProfile


class TodoListServiceTests(TestCase):
    def setUp(self):
        self.doctor_user = CustomUser.objects.create_user(
            user_type=choices.UserType.DOCTOR,
            phone="13800138222",
            wx_nickname="Dr. Todo",
        )
        self.doctor_profile = DoctorProfile.objects.create(
            user=self.doctor_user,
            name="待办医生",
            hospital="测试医院",
        )
        self.patient = PatientProfile.objects.create(
            phone="18600000333",
            name="待办患者",
            doctor=self.doctor_profile,
        )
        now = timezone.now()
        self.pending_alert = PatientAlert.objects.create(
            patient=self.patient,
            doctor=self.doctor_profile,
            event_type=AlertEventType.DATA,
            event_level=AlertLevel.MILD,
            event_title="血氧异常",
            event_content="血氧 94%",
            event_time=now,
            status=AlertStatus.PENDING,
        )
        self.completed_alert = PatientAlert.objects.create(
            patient=self.patient,
            doctor=self.doctor_profile,
            event_type=AlertEventType.BEHAVIOR,
            event_level=AlertLevel.MODERATE,
            event_title="用药未完成",
            event_content="连续3天未完成用药任务",
            event_time=now - timedelta(days=2),
            status=AlertStatus.COMPLETED,
        )

    def test_get_todo_page_filters_status(self):
        page = TodoListService.get_todo_page(
            user=self.doctor_user,
            status="pending",
        )
        self.assertEqual(len(page.object_list), 1)
        self.assertEqual(page.object_list[0]["id"], self.pending_alert.id)
        self.assertEqual(page.object_list[0]["status"], "pending")

    def test_get_todo_page_filters_status_list(self):
        escalated_alert = PatientAlert.objects.create(
            patient=self.patient,
            doctor=self.doctor_profile,
            event_type=AlertEventType.DATA,
            event_level=AlertLevel.MODERATE,
            event_title="心率异常",
            event_content="心率偏高",
            event_time=timezone.now(),
            status=AlertStatus.ESCALATED,
        )

        page = TodoListService.get_todo_page(
            user=self.doctor_user,
            status=["pending", "escalate"],
        )
        ids = {item["id"] for item in page.object_list}
        self.assertIn(self.pending_alert.id, ids)
        self.assertIn(escalated_alert.id, ids)
        self.assertNotIn(self.completed_alert.id, ids)

    def test_get_todo_page_status_list_all_passthrough(self):
        escalated_alert = PatientAlert.objects.create(
            patient=self.patient,
            doctor=self.doctor_profile,
            event_type=AlertEventType.DATA,
            event_level=AlertLevel.MODERATE,
            event_title="心率异常",
            event_content="心率偏高",
            event_time=timezone.now(),
            status=AlertStatus.ESCALATED,
        )

        page = TodoListService.get_todo_page(
            user=self.doctor_user,
            status=["all"],
        )
        ids = {item["id"] for item in page.object_list}
        self.assertEqual(
            ids,
            {self.pending_alert.id, self.completed_alert.id, escalated_alert.id},
        )

    def test_get_todo_page_filters_date_range(self):
        start_date = (timezone.localdate() - timedelta(days=1)).strftime("%Y-%m-%d")
        end_date = timezone.localdate().strftime("%Y-%m-%d")
        page = TodoListService.get_todo_page(
            user=self.doctor_user,
            start_date=start_date,
            end_date=end_date,
        )
        ids = {item["id"] for item in page.object_list}
        self.assertIn(self.pending_alert.id, ids)
        self.assertNotIn(self.completed_alert.id, ids)

    def test_get_todo_page_end_date_inclusive(self):
        end_date = timezone.localdate()
        end_dt = timezone.make_aware(datetime.combine(end_date, datetime.max.time()))
        next_day_dt = end_dt + timedelta(microseconds=1)

        in_range_alert = PatientAlert.objects.create(
            patient=self.patient,
            doctor=self.doctor_profile,
            event_type=AlertEventType.DATA,
            event_level=AlertLevel.MILD,
            event_title="血压异常",
            event_content="血压偏高",
            event_time=end_dt,
            status=AlertStatus.PENDING,
        )
        PatientAlert.objects.create(
            patient=self.patient,
            doctor=self.doctor_profile,
            event_type=AlertEventType.DATA,
            event_level=AlertLevel.MILD,
            event_title="血压异常(次日)",
            event_content="血压偏高",
            event_time=next_day_dt,
            status=AlertStatus.PENDING,
        )

        page = TodoListService.get_todo_page(
            user=self.doctor_user,
            start_date=end_date.strftime("%Y-%m-%d"),
            end_date=end_date.strftime("%Y-%m-%d"),
        )
        ids = {item["id"] for item in page.object_list}
        self.assertIn(in_range_alert.id, ids)

    def test_get_todo_page_returns_expected_fields(self):
        page = TodoListService.get_todo_page(user=self.doctor_user)
        item = page.object_list[0]
        self.assertIn("event_title", item)
        self.assertIn("event_type", item)
        self.assertIn("event_level", item)
        self.assertIn("event_time", item)
        self.assertIn("status", item)

    def test_count_abnormal_events_by_metric(self):
        now = timezone.now()
        PatientAlert.objects.create(
            patient=self.patient,
            doctor=self.doctor_profile,
            event_type=AlertEventType.DATA,
            event_level=AlertLevel.MILD,
            event_title="体温异常",
            event_content="体温 38.5",
            event_time=now,
            status=AlertStatus.PENDING,
            source_type="metric",
            source_payload={"metric_type": MetricType.BODY_TEMPERATURE},
        )

        count = TodoListService.count_abnormal_events(
            patient=self.patient,
            start_date=timezone.localdate() - timedelta(days=1),
            end_date=timezone.localdate(),
            type=MetricType.BODY_TEMPERATURE,
        )

        self.assertEqual(count, 1)

    def test_count_abnormal_events_by_questionnaire(self):
        now = timezone.now()
        PatientAlert.objects.create(
            patient=self.patient,
            doctor=self.doctor_profile,
            event_type=AlertEventType.QUESTIONNAIRE,
            event_level=AlertLevel.MODERATE,
            event_title="咳嗽与痰色评估异常",
            event_content="总分 6，分级 3 级",
            event_time=now,
            status=AlertStatus.PENDING,
            source_type="questionnaire",
            source_payload={"questionnaire_code": QuestionnaireCode.Q_COUGH},
        )

        count = TodoListService.count_abnormal_events(
            patient=self.patient,
            start_date=timezone.localdate() - timedelta(days=1),
            end_date=timezone.localdate(),
            type=QuestionnaireCode.Q_COUGH,
        )

        self.assertEqual(count, 1)

    def test_count_abnormal_events_end_date_inclusive(self):
        end_date = timezone.localdate()
        end_dt = timezone.make_aware(datetime.combine(end_date, datetime.max.time()))
        next_day_dt = end_dt + timedelta(microseconds=1)

        PatientAlert.objects.create(
            patient=self.patient,
            doctor=self.doctor_profile,
            event_type=AlertEventType.DATA,
            event_level=AlertLevel.MILD,
            event_title="体温异常",
            event_content="体温 38.5",
            event_time=end_dt,
            status=AlertStatus.PENDING,
            source_type="metric",
            source_payload={"metric_type": MetricType.BODY_TEMPERATURE},
        )
        PatientAlert.objects.create(
            patient=self.patient,
            doctor=self.doctor_profile,
            event_type=AlertEventType.DATA,
            event_level=AlertLevel.MILD,
            event_title="体温异常(次日)",
            event_content="体温 39.0",
            event_time=next_day_dt,
            status=AlertStatus.PENDING,
            source_type="metric",
            source_payload={"metric_type": MetricType.BODY_TEMPERATURE},
        )

        count = TodoListService.count_abnormal_events(
            patient=self.patient,
            start_date=end_date,
            end_date=end_date,
            type=MetricType.BODY_TEMPERATURE,
        )

        self.assertEqual(count, 1)
