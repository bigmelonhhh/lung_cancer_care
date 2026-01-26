"""generate_daily_tasks_for_date 调度函数测试。"""

from datetime import date, timedelta

from django.test import TestCase

from core.models import DailyTask, PlanItem, TreatmentCycle, choices
from core.service.task_scheduler import generate_daily_tasks_for_date
from users.models import PatientProfile


class TaskSchedulerTest(TestCase):
    """测试每日任务调度服务。"""

    def setUp(self) -> None:
        # 基础患者档案
        self.patient = PatientProfile.objects.create(
            phone="13800000000",
            name="测试患者",
        )

        # 一条疗程与其下的计划条目
        self.cycle_start_date = date(2025, 1, 1)
        self.cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="第1周期",
            start_date=self.cycle_start_date,
            cycle_days=21,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        self.plan_item = PlanItem.objects.create(
            cycle=self.cycle,
            category=choices.PlanItemCategory.MEDICATION,
            template_id=1,
            item_name="化疗用药A",
            drug_dosage="100mg",
            drug_usage="每日一次",
            schedule_days=[1, 3],
            status=choices.PlanItemStatus.ACTIVE,
        )

    def test_generate_daily_tasks_for_date_with_plan_and_monitoring(self):
        """同一天内生成计划任务，并保持幂等。"""

        task_date = self.cycle_start_date  # 对应 schedule_days 中的第 1 天

        # 第一次生成：应为计划生成两条任务（当天 + 未来）
        created_count = generate_daily_tasks_for_date(task_date)
        self.assertEqual(created_count, 2)

        tasks = DailyTask.objects.filter(patient=self.patient)
        self.assertEqual(tasks.count(), 2)

        # 计划任务校验
        plan_task = tasks.get(plan_item=self.plan_item, task_date=task_date)
        self.assertEqual(plan_task.task_type, choices.PlanItemCategory.MEDICATION)
        self.assertEqual(plan_task.title, self.plan_item.item_name)
        self.assertIn("100mg", plan_task.detail)
        self.assertIn("每日一次", plan_task.detail)
        self.assertEqual(plan_task.status, choices.TaskStatus.PENDING)

        future_task = tasks.get(
            plan_item=self.plan_item,
            task_date=self.cycle_start_date + timedelta(days=2),
        )
        self.assertEqual(future_task.status, choices.TaskStatus.NOT_STARTED)

        # 第二次调用同一天生成，应不再新增任务（幂等）
        created_count_again = generate_daily_tasks_for_date(task_date)
        self.assertEqual(created_count_again, 0)
        self.assertEqual(
            DailyTask.objects.filter(patient=self.patient).count(),
            2,
        )

    def test_cleanup_removed_schedule_days_deletes_future_tasks(self):
        task_date = self.cycle_start_date
        future_date = self.cycle_start_date + timedelta(days=2)

        generate_daily_tasks_for_date(task_date)
        self.assertTrue(
            DailyTask.objects.filter(
                plan_item=self.plan_item,
                task_date=future_date,
            ).exists()
        )

        self.plan_item.schedule_days = [1]
        self.plan_item.save(update_fields=["schedule_days"])

        generate_daily_tasks_for_date(task_date + timedelta(days=1))

        self.assertFalse(
            DailyTask.objects.filter(
                plan_item=self.plan_item,
                task_date=future_date,
            ).exists()
        )
        self.assertTrue(
            DailyTask.objects.filter(
                plan_item=self.plan_item,
                task_date=task_date,
            ).exists()
        )

    def test_cleanup_deleted_plan_item_deletes_future_tasks(self):
        task_date = self.cycle_start_date
        future_date = self.cycle_start_date + timedelta(days=2)

        generate_daily_tasks_for_date(task_date)
        self.assertTrue(
            DailyTask.objects.filter(
                plan_item=self.plan_item,
                task_date=future_date,
            ).exists()
        )

        self.plan_item.delete()

        generate_daily_tasks_for_date(task_date + timedelta(days=1))

        self.assertFalse(
            DailyTask.objects.filter(
                plan_item__isnull=True,
                task_date=future_date,
            ).exists()
        )
        self.assertTrue(
            DailyTask.objects.filter(
                task_date=task_date,
            ).exists()
        )

    def test_cleanup_terminated_cycle_deletes_not_started_tasks(self):
        task_date = self.cycle_start_date
        future_date = self.cycle_start_date + timedelta(days=2)

        generate_daily_tasks_for_date(task_date)
        self.assertTrue(
            DailyTask.objects.filter(
                plan_item=self.plan_item,
                task_date=future_date,
            ).exists()
        )

        self.cycle.status = choices.TreatmentCycleStatus.TERMINATED
        self.cycle.save(update_fields=["status"])

        generate_daily_tasks_for_date(task_date + timedelta(days=1))

        self.assertFalse(
            DailyTask.objects.filter(
                plan_item=self.plan_item,
                task_date=future_date,
            ).exists()
        )
        self.assertTrue(
            DailyTask.objects.filter(
                plan_item=self.plan_item,
                task_date=task_date,
            ).exists()
        )
