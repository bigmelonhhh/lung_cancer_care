from datetime import date

from django.test import TestCase

from core.models import DailyTask, MonitoringTemplate, PlanItem, TreatmentCycle, choices
from core.service import tasks as task_service
from health_data.models import MetricType
from users.models import PatientProfile


class TaskAdherenceServiceTest(TestCase):
    def setUp(self) -> None:
        self.patient = PatientProfile.objects.create(
            phone="13900000006",
            name="依从性测试患者",
        )
        self.cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="第1疗程",
            start_date=date(2025, 1, 1),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        self.start_date = date(2025, 1, 1)
        self.end_date = date(2025, 1, 2)

    def test_get_adherence_metrics_for_medication(self):
        DailyTask.objects.create(
            patient=self.patient,
            task_date=self.start_date,
            task_type=choices.PlanItemCategory.MEDICATION,
            title="药物A",
            status=choices.TaskStatus.COMPLETED,
        )
        DailyTask.objects.create(
            patient=self.patient,
            task_date=self.end_date,
            task_type=choices.PlanItemCategory.MEDICATION,
            title="药物B",
            status=choices.TaskStatus.PENDING,
        )
        DailyTask.objects.create(
            patient=self.patient,
            task_date=date(2025, 1, 3),
            task_type=choices.PlanItemCategory.MEDICATION,
            title="药物C",
            status=choices.TaskStatus.COMPLETED,
        )

        result = task_service.get_adherence_metrics(
            patient_id=self.patient.id,
            adherence_type=choices.PlanItemCategory.MEDICATION,
            start_date=self.start_date,
            end_date=self.end_date,
        )

        self.assertEqual(result["total"], 2)
        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["rate"], 0.5)

    def test_get_adherence_metrics_for_monitoring_metric(self):
        bp_template, _ = MonitoringTemplate.objects.get_or_create(
            code=MetricType.BLOOD_PRESSURE,
            defaults={
                "name": "血压监测",
                "metric_type": "blood_pressure",
                "is_active": True,
            },
        )
        hr_template, _ = MonitoringTemplate.objects.get_or_create(
            code=MetricType.HEART_RATE,
            defaults={
                "name": "心率监测",
                "metric_type": "heart_rate",
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
        hr_plan = PlanItem.objects.create(
            cycle=self.cycle,
            category=choices.PlanItemCategory.MONITORING,
            template_id=hr_template.id,
            item_name=hr_template.name,
            schedule_days=[1],
            status=choices.PlanItemStatus.ACTIVE,
        )
        DailyTask.objects.create(
            patient=self.patient,
            plan_item=bp_plan,
            task_date=self.start_date,
            task_type=choices.PlanItemCategory.MONITORING,
            title=bp_plan.item_name,
            status=choices.TaskStatus.COMPLETED,
        )
        DailyTask.objects.create(
            patient=self.patient,
            plan_item=bp_plan,
            task_date=self.end_date,
            task_type=choices.PlanItemCategory.MONITORING,
            title=bp_plan.item_name,
            status=choices.TaskStatus.PENDING,
        )
        DailyTask.objects.create(
            patient=self.patient,
            plan_item=hr_plan,
            task_date=self.start_date,
            task_type=choices.PlanItemCategory.MONITORING,
            title=hr_plan.item_name,
            status=choices.TaskStatus.COMPLETED,
        )

        result = task_service.get_adherence_metrics(
            patient_id=self.patient.id,
            adherence_type=MetricType.BLOOD_PRESSURE,
            start_date=self.start_date,
            end_date=self.end_date,
        )

        self.assertEqual(result["total"], 2)
        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["rate"], 0.5)

    def test_get_adherence_metrics_returns_none_when_no_tasks(self):
        result = task_service.get_adherence_metrics(
            patient_id=self.patient.id,
            adherence_type=choices.PlanItemCategory.QUESTIONNAIRE,
            start_date=self.start_date,
            end_date=self.end_date,
        )

        self.assertEqual(result["total"], 0)
        self.assertEqual(result["completed"], 0)
        self.assertIsNone(result["rate"])

    def test_new_metrics_are_included_in_combined_monitoring_adherence(self):
        for index, metric_type in enumerate(
            (
                MetricType.BLOOD_GLUCOSE,
                MetricType.BLOOD_KETONE,
                MetricType.URIC_ACID,
            )
        ):
            template, _ = MonitoringTemplate.objects.get_or_create(
                code=metric_type,
                defaults={
                    "name": f"监测{index}",
                    "metric_type": metric_type,
                    "is_active": True,
                },
            )
            plan = PlanItem.objects.create(
                cycle=self.cycle,
                category=choices.PlanItemCategory.MONITORING,
                template_id=template.id,
                item_name=template.name,
                schedule_days=[1],
                status=choices.PlanItemStatus.ACTIVE,
            )
            DailyTask.objects.create(
                patient=self.patient,
                plan_item=plan,
                task_date=self.start_date,
                task_type=choices.PlanItemCategory.MONITORING,
                title=template.name,
                status=(
                    choices.TaskStatus.COMPLETED
                    if index < 2
                    else choices.TaskStatus.PENDING
                ),
            )

        result = task_service.get_adherence_metrics(
            patient_id=self.patient.id,
            adherence_type=task_service.MONITORING_ADHERENCE_ALL,
            start_date=self.start_date,
            end_date=self.start_date,
        )

        self.assertEqual(result["total"], 3)
        self.assertEqual(result["completed"], 2)
        self.assertAlmostEqual(result["rate"], 2 / 3)

    def test_get_adherence_metrics_batch(self):
        bp_template, _ = MonitoringTemplate.objects.get_or_create(
            code=MetricType.BLOOD_PRESSURE,
            defaults={
                "name": "血压监测",
                "metric_type": "blood_pressure",
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
        DailyTask.objects.create(
            patient=self.patient,
            task_date=self.start_date,
            task_type=choices.PlanItemCategory.MEDICATION,
            title="药物A",
            status=choices.TaskStatus.COMPLETED,
        )
        DailyTask.objects.create(
            patient=self.patient,
            task_date=self.start_date,
            task_type=choices.PlanItemCategory.MONITORING,
            plan_item=bp_plan,
            title=bp_plan.item_name,
            status=choices.TaskStatus.COMPLETED,
        )
        DailyTask.objects.create(
            patient=self.patient,
            task_date=self.end_date,
            task_type=choices.PlanItemCategory.QUESTIONNAIRE,
            title="问卷A",
            status=choices.TaskStatus.PENDING,
        )

        result = task_service.get_adherence_metrics_batch(
            patient=self.patient,
            adherence_types=[
                choices.PlanItemCategory.MEDICATION,
                MetricType.BLOOD_PRESSURE,
                choices.PlanItemCategory.QUESTIONNAIRE,
            ],
            start_date=self.start_date,
            end_date=self.end_date,
        )

        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["type"], choices.PlanItemCategory.MEDICATION)
        self.assertEqual(result[0]["rate"], 1.0)
        self.assertEqual(result[1]["type"], MetricType.BLOOD_PRESSURE)
        self.assertEqual(result[1]["rate"], 1.0)
        self.assertEqual(result[2]["type"], choices.PlanItemCategory.QUESTIONNAIRE)
        self.assertEqual(result[2]["rate"], 0.0)
