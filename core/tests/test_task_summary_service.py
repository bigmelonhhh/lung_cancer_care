"""Task summary service tests."""

from datetime import date, datetime, timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

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
                "questionnaire_ids": [],
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

    def test_daily_plan_summary_returns_empty_when_date_outside_any_cycle(self):
        outside_date = date(2025, 2, 1)
        self.cycle.end_date = date(2025, 1, 10)
        self.cycle.save(update_fields=["end_date"])
        DailyTask.objects.create(
            patient=self.patient,
            task_date=date(2025, 1, 10),
            task_type=choices.PlanItemCategory.CHECKUP,
            title="复查提醒",
            status=choices.TaskStatus.PENDING,
        )
        summary = get_daily_plan_summary(self.patient, outside_date)
        self.assertEqual(summary, [])

    def test_daily_plan_summary_includes_cycle_boundaries(self):
        self.cycle.end_date = date(2025, 1, 10)
        self.cycle.save(update_fields=["end_date"])
        DailyTask.objects.create(
            patient=self.patient,
            task_date=self.cycle.start_date,
            task_type=choices.PlanItemCategory.CHECKUP,
            title="复查提醒",
            status=choices.TaskStatus.PENDING,
        )
        DailyTask.objects.create(
            patient=self.patient,
            task_date=self.cycle.end_date,
            task_type=choices.PlanItemCategory.CHECKUP,
            title="复查提醒",
            status=choices.TaskStatus.COMPLETED,
        )

        start_summary = get_daily_plan_summary(self.patient, self.cycle.start_date)
        self.assertTrue(start_summary)

        end_summary = get_daily_plan_summary(self.patient, self.cycle.end_date)
        self.assertTrue(end_summary)

    def test_default_date_uses_window_but_explicit_date_disables_window(self):
        self.cycle.end_date = date(2025, 1, 10)
        self.cycle.save(update_fields=["end_date"])
        today = date(2025, 1, 10)
        yesterday = today - timedelta(days=1)
        DailyTask.objects.create(
            patient=self.patient,
            task_date=yesterday,
            task_type=choices.PlanItemCategory.CHECKUP,
            title="复查提醒",
            status=choices.TaskStatus.PENDING,
        )
        DailyTask.objects.create(
            patient=self.patient,
            task_date=today,
            task_type=choices.PlanItemCategory.CHECKUP,
            title="复查提醒",
            status=choices.TaskStatus.COMPLETED,
        )
        DailyTask.objects.create(
            patient=self.patient,
            task_date=yesterday,
            task_type=choices.PlanItemCategory.QUESTIONNAIRE,
            plan_item=self.questionnaire_plan,
            title="问卷提醒",
            status=choices.TaskStatus.PENDING,
        )
        DailyTask.objects.create(
            patient=self.patient,
            task_date=today,
            task_type=choices.PlanItemCategory.QUESTIONNAIRE,
            plan_item=self.questionnaire_plan,
            title="问卷提醒",
            status=choices.TaskStatus.COMPLETED,
        )

        with patch("core.service.tasks.timezone.localdate", return_value=today):
            default_summary = get_daily_plan_summary(self.patient)
        default_checkup = next(
            (s for s in default_summary if s["task_type"] == int(choices.PlanItemCategory.CHECKUP)),
            None,
        )
        self.assertIsNotNone(default_checkup)
        self.assertEqual(default_checkup["status"], int(choices.TaskStatus.PENDING))

        default_q = next(
            (
                s
                for s in default_summary
                if s["task_type"] == int(choices.PlanItemCategory.QUESTIONNAIRE)
            ),
            None,
        )
        self.assertIsNotNone(default_q)
        self.assertEqual(default_q["questionnaire_ids"], [self.questionnaire.id])

        explicit_summary = get_daily_plan_summary(self.patient, today)
        explicit_checkup = next(
            (s for s in explicit_summary if s["task_type"] == int(choices.PlanItemCategory.CHECKUP)),
            None,
        )
        self.assertIsNotNone(explicit_checkup)
        self.assertEqual(explicit_checkup["status"], int(choices.TaskStatus.COMPLETED))

        explicit_q = next(
            (
                s
                for s in explicit_summary
                if s["task_type"] == int(choices.PlanItemCategory.QUESTIONNAIRE)
            ),
            None,
        )
        self.assertIsNotNone(explicit_q)
        self.assertEqual(explicit_q["questionnaire_ids"], [])

    def test_default_date_uses_recent_7_day_window(self):
        today = date(2025, 1, 10)
        within_window = today - timedelta(days=6)
        outside_window = today - timedelta(days=7)
        outside_checkup = DailyTask.objects.create(
            patient=self.patient,
            task_date=outside_window,
            task_type=choices.PlanItemCategory.CHECKUP,
            title="复查提醒",
            status=choices.TaskStatus.PENDING,
        )
        outside_questionnaire = DailyTask.objects.create(
            patient=self.patient,
            task_date=outside_window,
            task_type=choices.PlanItemCategory.QUESTIONNAIRE,
            plan_item=self.questionnaire_plan,
            title="问卷提醒",
            status=choices.TaskStatus.PENDING,
        )
        DailyTask.objects.create(
            patient=self.patient,
            task_date=within_window,
            task_type=choices.PlanItemCategory.CHECKUP,
            title="复查提醒",
            status=choices.TaskStatus.PENDING,
        )
        DailyTask.objects.create(
            patient=self.patient,
            task_date=within_window,
            task_type=choices.PlanItemCategory.QUESTIONNAIRE,
            plan_item=self.questionnaire_plan,
            title="问卷提醒",
            status=choices.TaskStatus.PENDING,
        )

        with patch("core.service.tasks.timezone.localdate", return_value=today):
            summary = get_daily_plan_summary(self.patient)

        checkup_summary = next(
            (s for s in summary if s["task_type"] == int(choices.PlanItemCategory.CHECKUP)),
            None,
        )
        self.assertIsNotNone(checkup_summary)
        self.assertEqual(checkup_summary["status"], int(choices.TaskStatus.PENDING))

        questionnaire_summary = next(
            (
                s
                for s in summary
                if s["task_type"] == int(choices.PlanItemCategory.QUESTIONNAIRE)
            ),
            None,
        )
        self.assertIsNotNone(questionnaire_summary)
        self.assertEqual(questionnaire_summary["questionnaire_ids"], [self.questionnaire.id])

        outside_checkup.refresh_from_db()
        outside_questionnaire.refresh_from_db()
        self.assertEqual(outside_checkup.status, choices.TaskStatus.TERMINATED)
        self.assertEqual(outside_questionnaire.status, choices.TaskStatus.TERMINATED)

    def test_default_date_shows_backlog_completed_only_on_completion_day(self):
        completed_day = date(2025, 1, 10)
        backlog_date = completed_day - timedelta(days=2)
        completed_at = timezone.make_aware(datetime(2025, 1, 10, 9, 0, 0))
        DailyTask.objects.create(
            patient=self.patient,
            task_date=backlog_date,
            task_type=choices.PlanItemCategory.CHECKUP,
            title="复查提醒",
            status=choices.TaskStatus.COMPLETED,
            completed_at=completed_at,
        )
        DailyTask.objects.create(
            patient=self.patient,
            task_date=backlog_date,
            task_type=choices.PlanItemCategory.QUESTIONNAIRE,
            plan_item=self.questionnaire_plan,
            title="问卷提醒",
            status=choices.TaskStatus.COMPLETED,
            completed_at=completed_at,
        )

        with patch("core.service.tasks.timezone.localdate", return_value=completed_day):
            summary_on_completed_day = get_daily_plan_summary(self.patient)

        self.assertTrue(
            any(
                item["task_type"] == int(choices.PlanItemCategory.CHECKUP)
                and item["status"] == int(choices.TaskStatus.COMPLETED)
                for item in summary_on_completed_day
            )
        )
        self.assertTrue(
            any(
                item["task_type"] == int(choices.PlanItemCategory.QUESTIONNAIRE)
                and item["status"] == int(choices.TaskStatus.COMPLETED)
                for item in summary_on_completed_day
            )
        )

        with patch(
            "core.service.tasks.timezone.localdate",
            return_value=completed_day + timedelta(days=1),
        ):
            summary_next_day = get_daily_plan_summary(self.patient)

        self.assertFalse(
            any(
                item["task_type"] == int(choices.PlanItemCategory.CHECKUP)
                for item in summary_next_day
            )
        )
        self.assertFalse(
            any(
                item["task_type"] == int(choices.PlanItemCategory.QUESTIONNAIRE)
                for item in summary_next_day
            )
        )

    def test_default_date_fallbacks_task_date_when_completed_at_missing(self):
        today = date(2025, 1, 10)
        yesterday = today - timedelta(days=1)
        DailyTask.objects.create(
            patient=self.patient,
            task_date=yesterday,
            task_type=choices.PlanItemCategory.CHECKUP,
            title="复查提醒",
            status=choices.TaskStatus.COMPLETED,
            completed_at=None,
        )
        DailyTask.objects.create(
            patient=self.patient,
            task_date=yesterday,
            task_type=choices.PlanItemCategory.QUESTIONNAIRE,
            plan_item=self.questionnaire_plan,
            title="问卷提醒",
            status=choices.TaskStatus.COMPLETED,
            completed_at=None,
        )

        with patch("core.service.tasks.timezone.localdate", return_value=today):
            summary = get_daily_plan_summary(self.patient)

        self.assertFalse(
            any(
                item["task_type"] == int(choices.PlanItemCategory.CHECKUP)
                for item in summary
            )
        )
        self.assertFalse(
            any(
                item["task_type"] == int(choices.PlanItemCategory.QUESTIONNAIRE)
                for item in summary
            )
        )
