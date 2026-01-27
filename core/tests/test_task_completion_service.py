"""Daily task completion service tests."""

from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from core.models import DailyTask, MonitoringTemplate, PlanItem, TreatmentCycle, choices
from core.service import tasks as task_service
from users.models import PatientProfile


class TaskCompletionServiceTest(TestCase):
    """验证计划任务完成状态更新逻辑。"""

    def setUp(self) -> None:
        self.patient = PatientProfile.objects.create(
            phone="13900000005",
            name="测试患者",
        )
        self.cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="第1疗程",
            start_date=date(2025, 1, 1),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        self.occurred_at = timezone.now()
        self.task_date = self.occurred_at.date()

    def test_complete_daily_medication_tasks_updates_all(self):
        task_a = DailyTask.objects.create(
            patient=self.patient,
            task_date=self.task_date,
            task_type=choices.PlanItemCategory.MEDICATION,
            title="药物A",
            status=choices.TaskStatus.PENDING,
        )
        DailyTask.objects.create(
            patient=self.patient,
            task_date=self.task_date,
            task_type=choices.PlanItemCategory.MEDICATION,
            title="药物B",
            status=choices.TaskStatus.PENDING,
        )
        DailyTask.objects.create(
            patient=self.patient,
            task_date=self.task_date + timedelta(days=1),
            task_type=choices.PlanItemCategory.MEDICATION,
            title="药物C",
            status=choices.TaskStatus.PENDING,
        )

        task_id = task_service.complete_daily_medication_tasks(
            patient_id=self.patient.id,
            occurred_at=self.occurred_at,
        )

        self.assertEqual(task_id, task_a.id)
        updated = DailyTask.objects.filter(
            patient=self.patient,
            task_date=self.task_date,
            task_type=choices.PlanItemCategory.MEDICATION,
            status=choices.TaskStatus.COMPLETED,
        )
        self.assertEqual(updated.count(), 2)

    def test_complete_daily_monitoring_tasks_updates_matching_metric(self):
        bp_template, _ = MonitoringTemplate.objects.get_or_create(
            code="M_BP",
            defaults={
                "name": "血压监测",
                "metric_type": "blood_pressure",
                "is_active": True,
            },
        )
        temp_template, _ = MonitoringTemplate.objects.get_or_create(
            code="M_TEMP",
            defaults={
                "name": "体温监测",
                "metric_type": "body_temperature",
                "is_active": True,
            },
        )
        bp_plan = PlanItem.objects.create(
            cycle=self.cycle,
            category=choices.PlanItemCategory.MONITORING,
            template_id=bp_template.id,
            item_name=bp_template.name,
            schedule_days=[1],
            status=choices.PlanItemStatus.ACTIVE,
        )
        temp_plan = PlanItem.objects.create(
            cycle=self.cycle,
            category=choices.PlanItemCategory.MONITORING,
            template_id=temp_template.id,
            item_name=temp_template.name,
            schedule_days=[1],
            status=choices.PlanItemStatus.ACTIVE,
        )
        DailyTask.objects.create(
            patient=self.patient,
            plan_item=bp_plan,
            task_date=self.task_date,
            task_type=choices.PlanItemCategory.MONITORING,
            title=bp_plan.item_name,
            status=choices.TaskStatus.PENDING,
        )
        DailyTask.objects.create(
            patient=self.patient,
            plan_item=temp_plan,
            task_date=self.task_date,
            task_type=choices.PlanItemCategory.MONITORING,
            title=temp_plan.item_name,
            status=choices.TaskStatus.PENDING,
        )

        updated_count = task_service.complete_daily_monitoring_tasks(
            patient_id=self.patient.id,
            metric_type="M_BP",
            occurred_at=self.occurred_at,
        )

        self.assertEqual(updated_count, 1)
        self.assertEqual(
            DailyTask.objects.filter(
                patient=self.patient,
                task_date=self.task_date,
                task_type=choices.PlanItemCategory.MONITORING,
                status=choices.TaskStatus.COMPLETED,
            ).count(),
            1,
        )

    def test_complete_daily_questionnaire_tasks_updates_all(self):
        task_a = DailyTask.objects.create(
            patient=self.patient,
            task_date=self.task_date,
            task_type=choices.PlanItemCategory.QUESTIONNAIRE,
            title="随访问卷",
            status=choices.TaskStatus.PENDING,
        )
        task_b = DailyTask.objects.create(
            patient=self.patient,
            task_date=self.task_date,
            task_type=choices.PlanItemCategory.QUESTIONNAIRE,
            title="满意度问卷",
            status=choices.TaskStatus.PENDING,
        )

        updated_count, task_id = task_service.complete_daily_questionnaire_tasks(
            patient_id=self.patient.id,
            occurred_at=self.occurred_at,
        )

        self.assertEqual(updated_count, 2)
        self.assertEqual(task_id, task_a.id)
        self.assertEqual(
            DailyTask.objects.filter(
                patient=self.patient,
                task_date=self.task_date,
                task_type=choices.PlanItemCategory.QUESTIONNAIRE,
                status=choices.TaskStatus.COMPLETED,
            ).count(),
            2,
        )

    def test_complete_daily_checkup_tasks_updates_all(self):
        DailyTask.objects.create(
            patient=self.patient,
            task_date=self.task_date,
            task_type=choices.PlanItemCategory.CHECKUP,
            title="复查CT",
            status=choices.TaskStatus.PENDING,
        )

        updated_count = task_service.complete_daily_checkup_tasks(
            patient_id=self.patient.id,
            occurred_at=self.occurred_at,
        )

        self.assertEqual(updated_count, 1)
        self.assertEqual(
            DailyTask.objects.filter(
                patient=self.patient,
                task_date=self.task_date,
                task_type=choices.PlanItemCategory.CHECKUP,
                status=choices.TaskStatus.COMPLETED,
            ).count(),
            1,
        )
