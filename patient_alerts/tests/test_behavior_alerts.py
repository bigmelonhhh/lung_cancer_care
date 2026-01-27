from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from core.models import DailyTask, MonitoringTemplate, PlanItem, TreatmentCycle, choices as core_choices
from health_data.models import MetricType
from patient_alerts.models import AlertEventType, AlertLevel, PatientAlert
from patient_alerts.services.behavior_alerts import BehaviorAlertService
from users.models import PatientProfile


class BehaviorAlertServiceTests(TestCase):
    def setUp(self):
        self.patient = PatientProfile.objects.create(phone="18600001000", name="行为测试")
        self.today = timezone.localdate()

    def _create_pending_tasks(self, *, task_type, dates, title, plan_item=None):
        for task_date in dates:
            DailyTask.objects.create(
                patient=self.patient,
                plan_item=plan_item,
                task_date=task_date,
                task_type=task_type,
                title=title,
                status=core_choices.TaskStatus.PENDING,
            )

    def test_medication_consecutive_missed_mild_creates_alert(self):
        as_of_date = self.today - timedelta(days=1)
        self._create_pending_tasks(
            task_type=core_choices.PlanItemCategory.MEDICATION,
            dates=[as_of_date],
            title="用药提醒",
        )

        BehaviorAlertService.run(as_of_date=as_of_date, patient_ids=[self.patient.id])

        alert = PatientAlert.objects.filter(
            patient=self.patient, event_type=AlertEventType.BEHAVIOR
        ).first()
        self.assertIsNotNone(alert)
        self.assertEqual(alert.event_level, AlertLevel.MILD)
        self.assertEqual(alert.event_title, "用药未完成")
        self.assertEqual(alert.event_content, "连续1天未完成用药任务")
        self.assertEqual(timezone.localdate(alert.event_time), as_of_date)

    def test_medication_consecutive_missed_creates_alert(self):
        as_of_date = self.today - timedelta(days=1)
        self._create_pending_tasks(
            task_type=core_choices.PlanItemCategory.MEDICATION,
            dates=[as_of_date - timedelta(days=offset) for offset in range(3)],
            title="用药提醒",
        )

        BehaviorAlertService.run(as_of_date=as_of_date, patient_ids=[self.patient.id])

        alert = PatientAlert.objects.filter(
            patient=self.patient, event_type=AlertEventType.BEHAVIOR
        ).first()
        self.assertIsNotNone(alert)
        self.assertEqual(alert.event_level, AlertLevel.MODERATE)
        self.assertEqual(alert.event_content, "连续3天未完成用药任务")

    def test_medication_consecutive_missed_severe_creates_alert(self):
        as_of_date = self.today - timedelta(days=1)
        self._create_pending_tasks(
            task_type=core_choices.PlanItemCategory.MEDICATION,
            dates=[as_of_date - timedelta(days=offset) for offset in range(7)],
            title="用药提醒",
        )

        BehaviorAlertService.run(as_of_date=as_of_date, patient_ids=[self.patient.id])

        alert = PatientAlert.objects.filter(
            patient=self.patient, event_type=AlertEventType.BEHAVIOR
        ).first()
        self.assertIsNotNone(alert)
        self.assertEqual(alert.event_level, AlertLevel.SEVERE)
        self.assertEqual(alert.event_content, "连续7天未完成用药任务")

    def test_medication_alert_escalates_to_higher_level(self):
        as_of_date = self.today - timedelta(days=1)
        self._create_pending_tasks(
            task_type=core_choices.PlanItemCategory.MEDICATION,
            dates=[as_of_date],
            title="用药提醒",
        )

        BehaviorAlertService.run(as_of_date=as_of_date, patient_ids=[self.patient.id])
        initial_alert = PatientAlert.objects.filter(
            patient=self.patient, event_type=AlertEventType.BEHAVIOR
        ).first()
        self.assertIsNotNone(initial_alert)

        self._create_pending_tasks(
            task_type=core_choices.PlanItemCategory.MEDICATION,
            dates=[as_of_date - timedelta(days=offset) for offset in range(1, 3)],
            title="用药提醒",
        )
        BehaviorAlertService.run(as_of_date=as_of_date, patient_ids=[self.patient.id])

        updated_alert = PatientAlert.objects.get(id=initial_alert.id)
        self.assertEqual(
            PatientAlert.objects.filter(
                patient=self.patient, event_type=AlertEventType.BEHAVIOR
            ).count(),
            1,
        )
        self.assertEqual(updated_alert.event_level, AlertLevel.MODERATE)
        self.assertEqual(updated_alert.event_content, "连续3天未完成用药任务")

    def test_monitoring_consecutive_missed_creates_alert(self):
        template, _ = MonitoringTemplate.objects.get_or_create(
            code=MetricType.BLOOD_OXYGEN,
            defaults={
                "name": "血氧",
                "metric_type": MetricType.BLOOD_OXYGEN,
            },
        )
        cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="测试疗程",
            start_date=self.today - timedelta(days=10),
        )
        plan_item = PlanItem.objects.create(
            cycle=cycle,
            category=core_choices.PlanItemCategory.MONITORING,
            template_id=template.id,
            item_name="血氧监测",
        )

        as_of_date = self.today - timedelta(days=1)
        self._create_pending_tasks(
            task_type=core_choices.PlanItemCategory.MONITORING,
            dates=[as_of_date - timedelta(days=offset) for offset in range(3)],
            title="血氧监测",
            plan_item=plan_item,
        )

        BehaviorAlertService.run(as_of_date=as_of_date, patient_ids=[self.patient.id])

        alert = PatientAlert.objects.filter(
            patient=self.patient, event_type=AlertEventType.BEHAVIOR
        ).first()
        self.assertIsNotNone(alert)
        self.assertEqual(alert.event_level, AlertLevel.MODERATE)
        self.assertEqual(alert.event_title, f"监测未完成-{template.name}")
        self.assertEqual(
            alert.event_content, f"连续3天未完成{template.name}监测"
        )

    def test_questionnaire_overdue_creates_alert(self):
        task_date = self.today - timedelta(days=4)
        DailyTask.objects.create(
            patient=self.patient,
            task_date=task_date,
            task_type=core_choices.PlanItemCategory.QUESTIONNAIRE,
            title="随访问卷",
            status=core_choices.TaskStatus.PENDING,
        )

        BehaviorAlertService.run(as_of_date=self.today - timedelta(days=1), patient_ids=[self.patient.id])

        alert = PatientAlert.objects.filter(
            patient=self.patient, event_type=AlertEventType.BEHAVIOR
        ).first()
        self.assertIsNotNone(alert)
        self.assertEqual(alert.event_level, AlertLevel.MODERATE)
        self.assertEqual(alert.event_title, "随访过期")
        self.assertIn("已逾期4天", alert.event_content)
        self.assertEqual(
            timezone.localdate(alert.event_time), task_date + timedelta(days=4)
        )

    def test_questionnaire_overdue_mild_creates_alert(self):
        task_date = self.today - timedelta(days=2)
        DailyTask.objects.create(
            patient=self.patient,
            task_date=task_date,
            task_type=core_choices.PlanItemCategory.QUESTIONNAIRE,
            title="随访问卷",
            status=core_choices.TaskStatus.PENDING,
        )

        BehaviorAlertService.run(
            as_of_date=self.today - timedelta(days=1), patient_ids=[self.patient.id]
        )

        alert = PatientAlert.objects.filter(
            patient=self.patient, event_type=AlertEventType.BEHAVIOR
        ).first()
        self.assertIsNotNone(alert)
        self.assertEqual(alert.event_level, AlertLevel.MILD)
        self.assertEqual(alert.event_title, "随访过期")
        self.assertIn("已逾期2天", alert.event_content)
        self.assertEqual(
            timezone.localdate(alert.event_time), task_date + timedelta(days=2)
        )

    def test_checkup_overdue_severe_creates_alert(self):
        task_date = self.today - timedelta(days=7)
        DailyTask.objects.create(
            patient=self.patient,
            task_date=task_date,
            task_type=core_choices.PlanItemCategory.CHECKUP,
            title="复查任务",
            status=core_choices.TaskStatus.PENDING,
        )

        BehaviorAlertService.run(
            as_of_date=self.today - timedelta(days=1), patient_ids=[self.patient.id]
        )

        alert = PatientAlert.objects.filter(
            patient=self.patient, event_type=AlertEventType.BEHAVIOR
        ).first()
        self.assertIsNotNone(alert)
        self.assertEqual(alert.event_level, AlertLevel.SEVERE)
        self.assertEqual(alert.event_title, "复查过期")
        self.assertIn("已逾期7天", alert.event_content)
        self.assertEqual(
            timezone.localdate(alert.event_time), task_date + timedelta(days=7)
        )
