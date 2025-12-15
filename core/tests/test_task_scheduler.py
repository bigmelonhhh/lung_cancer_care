"""generate_daily_tasks_for_date 调度函数测试。"""

from datetime import date

from django.test import TestCase

from core.models import (
    DailyTask,
    MonitoringConfig,
    PlanItem,
    TreatmentCycle,
    choices,
)
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
            item_name="化疗用药A",
            drug_dosage="100mg",
            drug_usage="每日一次",
            schedule_days=[1, 3],
            status=choices.PlanItemStatus.ACTIVE,
        )

        # 一条监测配置，仅开启体温监测，频率为每天一次
        self.monitoring_config = MonitoringConfig.objects.create(
            patient=self.patient,
            check_freq_days=1,
            enable_temp=True,
            enable_spo2=False,
            enable_weight=False,
            enable_bp=False,
            enable_step=False,
        )

    def test_generate_daily_tasks_for_date_with_plan_and_monitoring(self):
        """同一天内同时生成计划任务与监测任务，并保持幂等。"""

        task_date = self.cycle_start_date  # 对应 schedule_days 中的第 1 天

        # 第一次生成：应为计划 + 监测各生成一条任务
        created_count = generate_daily_tasks_for_date(task_date)
        self.assertEqual(created_count, 2)

        tasks = DailyTask.objects.filter(patient=self.patient, task_date=task_date)
        self.assertEqual(tasks.count(), 2)

        # 计划任务校验
        plan_task = tasks.get(plan_item=self.plan_item)
        self.assertEqual(plan_task.task_type, choices.PlanItemCategory.MEDICATION)
        self.assertEqual(plan_task.title, self.plan_item.item_name)
        self.assertIn("100mg", plan_task.detail)
        self.assertIn("每日一次", plan_task.detail)

        # 监测任务校验（plan_item 为空，类型为 MONITORING）
        monitoring_task = tasks.get(plan_item__isnull=True)
        self.assertEqual(monitoring_task.task_type, choices.PlanItemCategory.MONITORING)
        self.assertEqual(monitoring_task.title, "体温监测")
        self.assertEqual(monitoring_task.detail, "请记录今日体温。")

        # MonitoringConfig 的 last_gen_date_temp 应更新为当日
        self.monitoring_config.refresh_from_db()
        self.assertEqual(self.monitoring_config.last_gen_date_temp, task_date)

        # 第二次调用同一天生成，应不再新增任务（幂等）
        created_count_again = generate_daily_tasks_for_date(task_date)
        self.assertEqual(created_count_again, 0)
        self.assertEqual(
            DailyTask.objects.filter(patient=self.patient, task_date=task_date).count(),
            2,
        )

