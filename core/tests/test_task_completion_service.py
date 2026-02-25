"""Daily task completion service tests."""

from datetime import date, timedelta

from decimal import Decimal
from django.test import TestCase
from django.utils import timezone

from business_support.models import Device
from core.models import DailyTask, MonitoringTemplate, PlanItem, TreatmentCycle, choices
from core.service import tasks as task_service
from health_data.models import HealthMetric, MetricType
from health_data.services.health_metric import HealthMetricService
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
        self.occurred_at = timezone.localtime()
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

    def test_complete_daily_medication_tasks_allows_terminated_for_past_date(self):
        yesterday = self.task_date - timedelta(days=1)
        occurred_at = self.occurred_at - timedelta(days=1)
        task = DailyTask.objects.create(
            patient=self.patient,
            task_date=yesterday,
            task_type=choices.PlanItemCategory.MEDICATION,
            title="药物A",
            status=choices.TaskStatus.TERMINATED,
        )

        task_service.complete_daily_medication_tasks(
            patient_id=self.patient.id,
            occurred_at=occurred_at,
        )

        task.refresh_from_db()
        self.assertEqual(task.status, choices.TaskStatus.COMPLETED)

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

    def test_complete_daily_monitoring_tasks_allows_terminated_for_past_date(self):
        spo2_template, _ = MonitoringTemplate.objects.get_or_create(
            code="M_SPO2",
            defaults={
                "name": "血氧监测",
                "metric_type": "blood_oxygen",
                "is_active": True,
            },
        )
        spo2_plan = PlanItem.objects.create(
            cycle=self.cycle,
            category=choices.PlanItemCategory.MONITORING,
            template_id=spo2_template.id,
            item_name=spo2_template.name,
            schedule_days=[1],
            status=choices.PlanItemStatus.ACTIVE,
        )
        yesterday = self.task_date - timedelta(days=1)
        occurred_at = self.occurred_at - timedelta(days=1)
        task = DailyTask.objects.create(
            patient=self.patient,
            plan_item=spo2_plan,
            task_date=yesterday,
            task_type=choices.PlanItemCategory.MONITORING,
            title=spo2_plan.item_name,
            status=choices.TaskStatus.TERMINATED,
        )

        updated_count = task_service.complete_daily_monitoring_tasks(
            patient_id=self.patient.id,
            metric_type="M_SPO2",
            occurred_at=occurred_at,
        )

        task.refresh_from_db()
        self.assertEqual(updated_count, 1)
        self.assertEqual(task.status, choices.TaskStatus.COMPLETED)

    def test_save_manual_metric_completes_tasks_for_multiple_dates(self):
        weight_template, _ = MonitoringTemplate.objects.get_or_create(
            code="M_WEIGHT",
            defaults={
                "name": "体重监测",
                "metric_type": "weight",
                "is_active": True,
            },
        )
        weight_plan = PlanItem.objects.create(
            cycle=self.cycle,
            category=choices.PlanItemCategory.MONITORING,
            template_id=weight_template.id,
            item_name=weight_template.name,
            schedule_days=[1],
            status=choices.PlanItemStatus.ACTIVE,
        )
        yesterday = self.task_date - timedelta(days=1)
        task_yesterday = DailyTask.objects.create(
            patient=self.patient,
            plan_item=weight_plan,
            task_date=yesterday,
            task_type=choices.PlanItemCategory.MONITORING,
            title=weight_plan.item_name,
            status=choices.TaskStatus.TERMINATED,
        )
        task_today = DailyTask.objects.create(
            patient=self.patient,
            plan_item=weight_plan,
            task_date=self.task_date,
            task_type=choices.PlanItemCategory.MONITORING,
            title=weight_plan.item_name,
            status=choices.TaskStatus.PENDING,
        )

        HealthMetricService.save_manual_metric(
            patient_id=self.patient.id,
            metric_type=MetricType.WEIGHT,
            measured_at=self.occurred_at - timedelta(days=1),
            value_main=Decimal("1"),
        )
        HealthMetricService.save_manual_metric(
            patient_id=self.patient.id,
            metric_type=MetricType.WEIGHT,
            measured_at=self.occurred_at,
            value_main=Decimal("2"),
        )

        task_yesterday.refresh_from_db()
        task_today.refresh_from_db()
        self.assertEqual(task_yesterday.status, choices.TaskStatus.COMPLETED)
        self.assertEqual(task_today.status, choices.TaskStatus.COMPLETED)

    def test_save_manual_steps_completes_task_and_sets_task_id(self):
        steps_template, _ = MonitoringTemplate.objects.get_or_create(
            code="M_STEPS",
            defaults={
                "name": "步数监测",
                "metric_type": "steps",
                "is_active": True,
            },
        )
        steps_plan = PlanItem.objects.create(
            cycle=self.cycle,
            category=choices.PlanItemCategory.MONITORING,
            template_id=steps_template.id,
            item_name=steps_template.name,
            schedule_days=[1],
            status=choices.PlanItemStatus.ACTIVE,
        )
        task = DailyTask.objects.create(
            patient=self.patient,
            plan_item=steps_plan,
            task_date=self.task_date,
            task_type=choices.PlanItemCategory.MONITORING,
            title=steps_plan.item_name,
            status=choices.TaskStatus.PENDING,
        )

        metric = HealthMetricService.save_manual_metric(
            patient_id=self.patient.id,
            metric_type=MetricType.STEPS,
            measured_at=self.occurred_at,
            value_main=Decimal("1234"),
        )

        task.refresh_from_db()
        self.assertEqual(task.status, choices.TaskStatus.COMPLETED)
        self.assertEqual(metric.task_id, task.id)

    def test_handle_payload_steps_completes_task_and_backfills_task_id(self):
        steps_template, _ = MonitoringTemplate.objects.get_or_create(
            code="M_STEPS",
            defaults={
                "name": "步数监测",
                "metric_type": "steps",
                "is_active": True,
            },
        )
        steps_plan = PlanItem.objects.create(
            cycle=self.cycle,
            category=choices.PlanItemCategory.MONITORING,
            template_id=steps_template.id,
            item_name=steps_template.name,
            schedule_days=[1],
            status=choices.PlanItemStatus.ACTIVE,
        )
        task = DailyTask.objects.create(
            patient=self.patient,
            plan_item=steps_plan,
            task_date=self.task_date,
            task_type=choices.PlanItemCategory.MONITORING,
            title=steps_plan.item_name,
            status=choices.TaskStatus.PENDING,
        )
        device = Device.objects.create(
            sn="SN-STEPS-TEST-001",
            imei="IMEI-STEPS-TEST-001",
            current_patient=self.patient,
        )

        payload = {
            "type": "WATCH",
            "deviceNo": device.imei,
            "recordTime": int(self.occurred_at.timestamp() * 1000),
            "watchData": {"pedo": {"step": 1234}},
        }

        HealthMetricService.handle_payload(payload)

        task.refresh_from_db()
        self.assertEqual(task.status, choices.TaskStatus.COMPLETED)

        metric = HealthMetric.objects.get(
            patient=self.patient,
            metric_type=MetricType.STEPS,
        )
        self.assertEqual(metric.task_id, task.id)

        payload["watchData"]["pedo"]["step"] = 2345
        HealthMetricService.handle_payload(payload)
        metric.refresh_from_db()
        self.assertEqual(metric.value_main, Decimal("2345"))
        self.assertEqual(metric.task_id, task.id)
