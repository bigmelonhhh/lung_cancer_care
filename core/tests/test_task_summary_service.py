"""Task summary service tests."""

from datetime import date

from django.test import TestCase

from core.models import DailyTask, PlanItem, Questionnaire, TreatmentCycle, choices
from core.service.tasks import get_daily_plan_summary
from users.models import PatientProfile


class TaskSummaryServiceTest(TestCase):
    """验证患者端当天计划摘要的聚合规则。"""

    def setUp(self) -> None:
        self.patient = PatientProfile.objects.create(
            phone="13900000004",
            name="测试患者",
        )
        self.task_date = date(2025, 1, 1)
        self.cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="第1疗程",
            start_date=self.task_date,
            cycle_days=21,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        self.questionnaire = Questionnaire.objects.create(
            name="随访问卷A",
            code="Q_TEST_A",
            is_active=True,
        )
        self.questionnaire_plan = PlanItem.objects.create(
            cycle=self.cycle,
            category=choices.PlanItemCategory.QUESTIONNAIRE,
            template_id=self.questionnaire.id,
            item_name=self.questionnaire.name,
            schedule_days=[1],
            status=choices.PlanItemStatus.ACTIVE,
        )

    def test_daily_plan_summary_aggregation(self):
        DailyTask.objects.create(
            patient=self.patient,
            task_date=self.task_date,
            task_type=choices.PlanItemCategory.MEDICATION,
            title="药物A",
            status=choices.TaskStatus.COMPLETED,
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
            task_date=self.task_date,
            task_type=choices.PlanItemCategory.CHECKUP,
            title="复查CT",
            status=choices.TaskStatus.PENDING,
        )
        DailyTask.objects.create(
            patient=self.patient,
            task_date=self.task_date,
            task_type=choices.PlanItemCategory.QUESTIONNAIRE,
            plan_item=self.questionnaire_plan,
            title="随访问卷",
            status=choices.TaskStatus.COMPLETED,
        )
        DailyTask.objects.create(
            patient=self.patient,
            task_date=self.task_date,
            task_type=choices.PlanItemCategory.MONITORING,
            title="测量体温",
            status=choices.TaskStatus.PENDING,
        )
        DailyTask.objects.create(
            patient=self.patient,
            task_date=self.task_date,
            task_type=choices.PlanItemCategory.MONITORING,
            title="测量血氧",
            status=choices.TaskStatus.COMPLETED,
        )

        summary = get_daily_plan_summary(self.patient, self.task_date)

        self.assertEqual(len(summary), 5)
        self.assertEqual(
            summary[0],
            {
                "task_type": int(choices.PlanItemCategory.MEDICATION),
                "status": int(choices.TaskStatus.PENDING),
                "title": "用药提醒",
            },
        )
        self.assertEqual(
            summary[1],
            {
                "task_type": int(choices.PlanItemCategory.CHECKUP),
                "status": int(choices.TaskStatus.PENDING),
                "title": "复查提醒",
            },
        )
        self.assertEqual(
            summary[2],
            {
                "task_type": int(choices.PlanItemCategory.QUESTIONNAIRE),
                "status": int(choices.TaskStatus.COMPLETED),
                "title": "问卷提醒",
                "questionnaire_ids": [self.questionnaire.id],
            },
        )
        self.assertEqual(
            summary[3],
            {
                "task_type": int(choices.PlanItemCategory.MONITORING),
                "status": int(choices.TaskStatus.PENDING),
                "title": "测量体温",
            },
        )
        self.assertEqual(
            summary[4],
            {
                "task_type": int(choices.PlanItemCategory.MONITORING),
                "status": int(choices.TaskStatus.COMPLETED),
                "title": "测量血氧",
            },
        )

    def test_daily_plan_summary_questionnaire_ids_unique(self):
        second_questionnaire = Questionnaire.objects.create(
            name="随访问卷B",
            code="Q_TEST_B",
            is_active=True,
        )
        second_plan = PlanItem.objects.create(
            cycle=self.cycle,
            category=choices.PlanItemCategory.QUESTIONNAIRE,
            template_id=second_questionnaire.id,
            item_name=second_questionnaire.name,
            schedule_days=[1],
            status=choices.PlanItemStatus.ACTIVE,
        )
        DailyTask.objects.create(
            patient=self.patient,
            task_date=self.task_date,
            task_type=choices.PlanItemCategory.QUESTIONNAIRE,
            plan_item=self.questionnaire_plan,
            title="随访问卷A",
            status=choices.TaskStatus.PENDING,
        )
        DailyTask.objects.create(
            patient=self.patient,
            task_date=self.task_date,
            task_type=choices.PlanItemCategory.QUESTIONNAIRE,
            plan_item=self.questionnaire_plan,
            title="随访问卷A",
            status=choices.TaskStatus.COMPLETED,
        )
        DailyTask.objects.create(
            patient=self.patient,
            task_date=self.task_date,
            task_type=choices.PlanItemCategory.QUESTIONNAIRE,
            plan_item=second_plan,
            title="随访问卷B",
            status=choices.TaskStatus.PENDING,
        )

        summary = get_daily_plan_summary(self.patient, self.task_date)

        questionnaire_summary = summary[0]
        self.assertEqual(
            questionnaire_summary["questionnaire_ids"],
            [self.questionnaire.id, second_questionnaire.id],
        )

    def test_daily_plan_summary_questionnaire_ids_skips_missing_plan_item(self):
        DailyTask.objects.create(
            patient=self.patient,
            task_date=self.task_date,
            task_type=choices.PlanItemCategory.QUESTIONNAIRE,
            title="随访问卷",
            status=choices.TaskStatus.PENDING,
        )

        summary = get_daily_plan_summary(self.patient, self.task_date)

        questionnaire_summary = summary[0]
        self.assertEqual(questionnaire_summary["questionnaire_ids"], [])
