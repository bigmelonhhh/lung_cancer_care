"""PlanItemService expired cycle validations."""

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from core.models import CheckupLibrary, Medication, MonitoringTemplate, PlanItem, Questionnaire, TreatmentCycle, choices
from core.service.plan_item import PlanItemService
from users import choices as user_choices
from users.models import PatientProfile

User = get_user_model()


class PlanItemServiceExpiredCycleTest(TestCase):
    """确保已终止疗程不允许修改计划。"""

    def setUp(self) -> None:
        self.actor = User.objects.create_user(
            username="doctor_user",
            password="password",
            user_type=user_choices.UserType.DOCTOR,
            phone="13900000003",
        )
        
        self.patient = PatientProfile.objects.create(
            phone="13900000001",
            name="测试患者",
        )
        self.cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="已终止疗程",
            start_date=date.today() - timedelta(days=10),
            cycle_days=7,
            status=choices.TreatmentCycleStatus.TERMINATED,
        )
        self.medication = Medication.objects.create(
            name="测试药物",
            name_abbr="CSYW",
            default_dosage="10mg",
            default_frequency="qd",
            is_active=True,
        )
        self.plan_item = PlanItem.objects.create(
            cycle=self.cycle,
            category=choices.PlanItemCategory.MEDICATION,
            template_id=self.medication.id,
            item_name=self.medication.name,
            drug_dosage="5mg",
            drug_usage="qd",
            schedule_days=[1, 2],
            status=choices.PlanItemStatus.ACTIVE,
            created_by=self.actor,
            updated_by=self.actor,
        )

    def test_toggle_item_status_rejects_finished_cycle(self):
        with self.assertRaisesMessage(ValidationError, "不能修过已终止的状态。"):
            PlanItemService.toggle_item_status(
                cycle_id=self.cycle.id,
                category=choices.PlanItemCategory.MEDICATION,
                library_id=self.medication.id,
                enable=True,
                user=self.actor,
            )

    def test_update_item_field_rejects_finished_cycle(self):
        with self.assertRaisesMessage(ValidationError, "不能修过已终止的状态。"):
            PlanItemService.update_item_field(self.plan_item.id, "drug_dosage", "20mg", self.actor)

    def test_toggle_schedule_day_rejects_finished_cycle(self):
        with self.assertRaisesMessage(ValidationError, "不能修过已终止的状态。"):
            PlanItemService.toggle_schedule_day(self.plan_item.id, 1, True, self.actor)


class PlanItemServiceCycleDayNormalizationTest(TestCase):
    def setUp(self) -> None:
        self.actor = User.objects.create_user(
            username="doctor_user_cycle_days",
            password="password",
            user_type=user_choices.UserType.DOCTOR,
            phone="13900000013",
        )
        self.patient = PatientProfile.objects.create(
            phone="13900000011",
            name="测试患者-周期天数",
        )

    def test_toggle_item_status_clips_template_days_to_cycle_days(self):
        cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="21天疗程",
            start_date=date.today(),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        medication = Medication.objects.create(
            name="测试药物-裁剪模板",
            name_abbr="CSYWJMB",
            default_dosage="10mg",
            default_frequency="qd",
            schedule_days_template=[1, 8, 15, 22, 28],
            is_active=True,
        )

        plan = PlanItemService.toggle_item_status(
            cycle_id=cycle.id,
            category=choices.PlanItemCategory.MEDICATION,
            library_id=medication.id,
            enable=True,
            user=self.actor,
        )

        self.assertIsNotNone(plan)
        self.assertEqual(plan.schedule_days, [1, 8, 15])

    def test_get_cycle_plan_view_clips_existing_plan_days_to_cycle_days(self):
        cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="21天疗程-已有计划",
            start_date=date.today(),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        medication = Medication.objects.create(
            name="测试药物-已有计划",
            name_abbr="CSYWYYJH",
            default_dosage="10mg",
            default_frequency="qd",
            schedule_days_template=[1, 8, 15, 22],
            is_active=True,
        )
        PlanItem.objects.create(
            cycle=cycle,
            category=choices.PlanItemCategory.MEDICATION,
            template_id=medication.id,
            item_name=medication.name,
            drug_dosage="10mg",
            drug_usage="qd",
            schedule_days=[1, 15, 22, 30],
            status=choices.PlanItemStatus.ACTIVE,
            created_by=self.actor,
            updated_by=self.actor,
        )

        plan_view = PlanItemService.get_cycle_plan_view(cycle.id)
        medication_payload = next(
            item for item in plan_view["medications"] if item["library_id"] == medication.id
        )

        self.assertEqual(medication_payload["schedule_days"], [1, 15])
        self.assertEqual(medication_payload["schedule_days_template"], [1, 8, 15])

    def test_toggle_schedule_day_allows_last_day_and_rejects_overflow_day(self):
        cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="28天疗程",
            start_date=date.today(),
            cycle_days=28,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        medication = Medication.objects.create(
            name="测试药物-28天",
            name_abbr="CSYW28T",
            default_dosage="10mg",
            default_frequency="qd",
            schedule_days_template=[1, 28],
            is_active=True,
        )
        plan_item = PlanItem.objects.create(
            cycle=cycle,
            category=choices.PlanItemCategory.MEDICATION,
            template_id=medication.id,
            item_name=medication.name,
            drug_dosage="10mg",
            drug_usage="qd",
            schedule_days=[1],
            status=choices.PlanItemStatus.ACTIVE,
            created_by=self.actor,
            updated_by=self.actor,
        )

        updated_plan = PlanItemService.toggle_schedule_day(plan_item.id, 28, True, self.actor)
        self.assertEqual(updated_plan.schedule_days, [1, 28])

        with self.assertRaisesMessage(ValidationError, "执行日需在 1~28 范围内。"):
            PlanItemService.toggle_schedule_day(plan_item.id, 29, True, self.actor)


class PlanItemServiceCloneCyclePlanTest(TestCase):
    def setUp(self) -> None:
        self.actor = User.objects.create_user(
            username="doctor_user_clone_plan",
            password="password",
            user_type=user_choices.UserType.DOCTOR,
            phone="13900000023",
        )
        self.patient = PatientProfile.objects.create(
            phone="13900000021",
            name="测试患者-复制计划",
        )

    def test_clone_cycle_plan_copies_all_categories_and_clips_days(self):
        source_cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="参考疗程",
            start_date=date.today(),
            cycle_days=28,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        target_cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="目标疗程",
            start_date=date.today() + timedelta(days=30),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )

        medication = Medication.objects.create(
            name="复制药物",
            name_abbr="FZYW",
            default_dosage="10mg",
            default_frequency="qd",
            is_active=True,
        )
        checkup = CheckupLibrary.objects.create(
            name="复制复查",
            code="COPY_CHECKUP",
            is_active=True,
        )
        questionnaire = Questionnaire.objects.create(
            name="复制问卷",
            code="COPY_QUESTIONNAIRE",
            is_active=True,
        )
        monitoring = MonitoringTemplate.objects.create(
            name="复制监测",
            code="COPY_MONITORING",
            is_active=True,
        )

        PlanItem.objects.create(
            cycle=source_cycle,
            category=choices.PlanItemCategory.MEDICATION,
            template_id=medication.id,
            item_name=medication.name,
            drug_dosage="20mg",
            drug_usage="bid",
            schedule_days=[1, 8, 15, 28],
            status=choices.PlanItemStatus.ACTIVE,
            priority_level=choices.PriorityLevel.FIRST_LINE,
            created_by=self.actor,
            updated_by=self.actor,
        )
        PlanItem.objects.create(
            cycle=source_cycle,
            category=choices.PlanItemCategory.CHECKUP,
            template_id=checkup.id,
            item_name=checkup.name,
            schedule_days=[3, 21, 28],
            status=choices.PlanItemStatus.ACTIVE,
            created_by=self.actor,
            updated_by=self.actor,
        )
        PlanItem.objects.create(
            cycle=source_cycle,
            category=choices.PlanItemCategory.QUESTIONNAIRE,
            template_id=questionnaire.id,
            item_name=questionnaire.name,
            schedule_days=[7, 14, 28],
            status=choices.PlanItemStatus.DISABLED,
            created_by=self.actor,
            updated_by=self.actor,
        )
        PlanItem.objects.create(
            cycle=source_cycle,
            category=choices.PlanItemCategory.MONITORING,
            template_id=monitoring.id,
            item_name=monitoring.name,
            schedule_days=[1, 10, 22],
            status=choices.PlanItemStatus.ACTIVE,
            created_by=self.actor,
            updated_by=self.actor,
        )

        copied_count = PlanItemService.clone_cycle_plan(source_cycle, target_cycle, self.actor)

        self.assertEqual(copied_count, 4)
        cloned_items = list(PlanItem.objects.filter(cycle=target_cycle).order_by("category"))
        self.assertEqual(len(cloned_items), 4)
        self.assertEqual(cloned_items[0].schedule_days, [1, 8, 15])
        self.assertEqual(cloned_items[0].drug_dosage, "20mg")
        self.assertEqual(cloned_items[0].drug_usage, "bid")
        self.assertEqual(cloned_items[0].priority_level, choices.PriorityLevel.FIRST_LINE)
        self.assertEqual(cloned_items[1].schedule_days, [3, 21])
        self.assertEqual(cloned_items[2].schedule_days, [7, 14])
        self.assertEqual(cloned_items[2].status, choices.PlanItemStatus.DISABLED)
        self.assertEqual(cloned_items[3].schedule_days, [1, 10])

    def test_clone_cycle_plan_returns_zero_when_source_has_no_plan_items(self):
        source_cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="空参考疗程",
            start_date=date.today(),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        target_cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="空目标疗程",
            start_date=date.today() + timedelta(days=30),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )

        copied_count = PlanItemService.clone_cycle_plan(source_cycle, target_cycle, self.actor)

        self.assertEqual(copied_count, 0)
        self.assertFalse(PlanItem.objects.filter(cycle=target_cycle).exists())
