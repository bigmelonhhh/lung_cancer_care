from django.test import TestCase, RequestFactory
from django.urls import reverse
from unittest.mock import patch, MagicMock
from web_patient.views.plan import management_plan
from users.models import PatientProfile, CustomUser
from users import choices
from core.models import TreatmentCycle, DailyTask
from core.models import choices as core_choices
from health_data.models import MetricType
from django.utils import timezone
import datetime
from decimal import Decimal
from market.models import Product, Order

class ManagementPlanViewTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = CustomUser.objects.create_user(
            username='testpatient', 
            password='password',
            user_type=choices.UserType.PATIENT,
            wx_openid='test_openid_123'
        )
        self.patient = PatientProfile.objects.create(user=self.user, name="Test Patient")
        product = Product.objects.create(
            name="VIP 服务包",
            price=Decimal("199.00"),
            duration_days=30,
            is_active=True,
        )
        Order.objects.create(
            patient=self.patient,
            product=product,
            amount=Decimal("199.00"),
            status=Order.Status.PAID,
            paid_at=timezone.now(),
        )
        self.url = reverse('web_patient:management_plan')

    @patch('web_patient.views.plan.get_daily_plan_summary')
    def test_management_plan_context(self, mock_get_plan):
        # 1. Mock Plan Data (In Plan)
        mock_get_plan.return_value = [
            {"task_type": "MEDICATION", "title": "按时用药", "status": 0}, # Incomplete
            {"task_type": "MONITORING", "title": "测量体温", "status": 0},
            {"task_type": "MONITORING", "title": "测量血压", "status": 0},
        ]

        # Create request
        request = self.factory.get(self.url)
        request.user = self.user
        request.patient = self.patient

        # Call view
        response = management_plan(request)

        # Check response
        self.assertEqual(response.status_code, 200)
        
        # Verify context data
        # Note: We can't easily access context from response when using RequestFactory and render directly.
        # So we should use client.get if we want to check context, or inspect the rendered content if simple.
        # Better: Use self.client.force_login(self.user)
        
    @patch('web_patient.views.plan.get_daily_plan_summary')
    def test_management_plan_view_logic(self, mock_get_plan):
        self.client.force_login(self.user)
        
        # Scenario 1: Medication In Plan, Incomplete
        # Scenario 2: Temp Task Completed
        # Scenario 3: BP In Plan, Incomplete
        # Scenario 4: SpO2 Not In Plan
        
        mock_get_plan.return_value = [
            {"task_type": "MEDICATION", "title": "按时用药", "status": 0},
            {"task_type": "MONITORING", "title": "测量体温", "status": 1},
            {"task_type": "MONITORING", "title": "测量血压", "status": 0},
        ]
        
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        
        context = response.context
        medication_plan = context['medication_plan']
        monitoring_plan = context['monitoring_plan']
        
        # Check Medication
        # Assuming we find one medication item
        self.assertTrue(len(medication_plan) > 0)
        self.assertEqual(medication_plan[0]['status'], 'incomplete') # Based on plan status or data? 
        # Requirement: "If indicator in plan... Data entered: completed" - this applies to monitoring?
        # For medication: "State update range: #1 Medication, #2 Monitoring"
        # Usually medication status comes from task status directly (clicked "Take Meds").
        # But let's assume if task status is 1 (completed), it is completed.
        
        # Check Monitoring
        # Temp: completed task status is displayed directly.
        temp_task = next((t for t in monitoring_plan if t['title'] == '测量体温'), None)
        self.assertIsNotNone(temp_task)
        self.assertEqual(temp_task['status'], 'completed')
        
        # BP: pending task status is displayed as incomplete.
        bp_task = next((t for t in monitoring_plan if t['title'] == '测量血压/心率'), None)
        self.assertIsNotNone(bp_task)
        self.assertEqual(bp_task['status'], 'incomplete')
        
        # SpO2: Not in plan = Empty status
        spo2_task = next((t for t in monitoring_plan if t['title'] == '测量血氧'), None)
        self.assertIsNotNone(spo2_task)
        self.assertEqual(spo2_task['status'], '')
        self.assertEqual(spo2_task['status_text'], '今日无计划')

    @patch('web_patient.views.plan.get_daily_plan_summary')
    def test_new_monitoring_categories_resolve_by_metric_type_and_keep_order(
        self, mock_get_plan
    ):
        self.client.force_login(self.user)
        mock_get_plan.return_value = [
            {
                "task_type": int(core_choices.PlanItemCategory.MONITORING),
                "title": "无意义旧标题",
                "metric_type": MetricType.BLOOD_KETONE,
                "status": int(core_choices.TaskStatus.PENDING),
            },
            {
                "task_type": int(core_choices.PlanItemCategory.MONITORING),
                "title": "另一个旧标题",
                "metric_type": MetricType.BLOOD_GLUCOSE,
                "status": int(core_choices.TaskStatus.COMPLETED),
            },
        ]
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        monitoring_plan = response.context["monitoring_plan"]
        self.assertEqual(
            [item["title"] for item in monitoring_plan],
            [
                "测量血氧",
                "测量血压/心率",
                "测量体温",
                "测量体重",
                "测量步数",
                "测量血糖",
                "测量血酮",
                "测量尿酸",
            ],
        )
        self.assertEqual(monitoring_plan[5]["status"], "completed")
        self.assertEqual(monitoring_plan[6]["status"], "incomplete")
        self.assertEqual(monitoring_plan[7]["status_text"], "今日无计划")

    @patch('web_patient.views.plan.get_daily_plan_summary')
    def test_new_monitoring_categories_fallback_to_legacy_titles(
        self, mock_get_plan
    ):
        self.client.force_login(self.user)
        mock_get_plan.return_value = [
            {
                "task_type": int(core_choices.PlanItemCategory.MONITORING),
                "title": title,
                "status": int(core_choices.TaskStatus.PENDING),
            }
            for title in ("血糖监测", "血酮监测", "尿酸监测")
        ]
        response = self.client.get(self.url)

        statuses = {
            item["title"]: item["status"]
            for item in response.context["monitoring_plan"]
        }
        self.assertTrue(
            {"测量血糖", "测量血酮", "测量尿酸"}.issubset(statuses),
            statuses,
        )
        self.assertEqual(statuses["测量血糖"], "incomplete")
        self.assertEqual(statuses["测量血酮"], "incomplete")
        self.assertEqual(statuses["测量尿酸"], "incomplete")

    @patch('web_patient.views.plan.get_daily_plan_summary')
    def test_blood_pressure_and_heart_rate_remain_one_group(
        self, mock_get_plan
    ):
        # 仅心率任务完成时，血压/心率计划不算完成（需双项齐全）。
        self.client.force_login(self.user)
        mock_get_plan.return_value = [
            {
                "task_type": int(core_choices.PlanItemCategory.MONITORING),
                "title": "血压监测",
                "metric_type": MetricType.BLOOD_PRESSURE,
                "status": int(core_choices.TaskStatus.PENDING),
            },
            {
                "task_type": int(core_choices.PlanItemCategory.MONITORING),
                "title": "心率监测",
                "metric_type": MetricType.HEART_RATE,
                "status": int(core_choices.TaskStatus.COMPLETED),
            },
        ]
        response = self.client.get(self.url)

        bp_hr_items = [
            item
            for item in response.context["monitoring_plan"]
            if item["title"] == "测量血压/心率"
        ]
        self.assertEqual(len(bp_hr_items), 1)
        self.assertEqual(bp_hr_items[0]["status"], "incomplete")

    @patch('web_patient.views.plan.get_daily_plan_summary')
    def test_blood_pressure_and_heart_rate_require_all_tasks_completed(
        self, mock_get_plan
    ):
        # 血压、心率任务全部完成时，血压/心率计划才算完成。
        self.client.force_login(self.user)
        mock_get_plan.return_value = [
            {
                "task_type": int(core_choices.PlanItemCategory.MONITORING),
                "title": "血压监测",
                "metric_type": MetricType.BLOOD_PRESSURE,
                "status": int(core_choices.TaskStatus.COMPLETED),
            },
            {
                "task_type": int(core_choices.PlanItemCategory.MONITORING),
                "title": "心率监测",
                "metric_type": MetricType.HEART_RATE,
                "status": int(core_choices.TaskStatus.COMPLETED),
            },
        ]
        response = self.client.get(self.url)

        bp_hr_items = [
            item
            for item in response.context["monitoring_plan"]
            if item["title"] == "测量血压/心率"
        ]
        self.assertEqual(len(bp_hr_items), 1)
        self.assertEqual(bp_hr_items[0]["status"], "completed")

    def test_management_plan_treatment_courses_from_cycles_and_tasks(self):
        self.client.force_login(self.user)
        today = timezone.localdate()

        cycle_current = TreatmentCycle.objects.create(
            patient=self.patient,
            name="第三疗程",
            start_date=today - datetime.timedelta(days=10),
            end_date=today + datetime.timedelta(days=10),
            cycle_days=21,
            status=core_choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        cycle_history = TreatmentCycle.objects.create(
            patient=self.patient,
            name="第二疗程",
            start_date=today - datetime.timedelta(days=40),
            end_date=today - datetime.timedelta(days=20),
            cycle_days=21,
            status=core_choices.TreatmentCycleStatus.COMPLETED,
        )

        date_recent = today - datetime.timedelta(days=1)
        date_future = today + datetime.timedelta(days=3)
        date_old = today - datetime.timedelta(days=20)

        DailyTask.objects.create(
            patient=self.patient,
            task_date=date_recent,
            task_type=core_choices.PlanItemCategory.QUESTIONNAIRE,
            title="问卷提醒",
            status=core_choices.TaskStatus.PENDING,
        )
        DailyTask.objects.create(
            patient=self.patient,
            task_date=date_recent,
            task_type=core_choices.PlanItemCategory.CHECKUP,
            title="复查提醒",
            status=core_choices.TaskStatus.COMPLETED,
        )
        DailyTask.objects.create(
            patient=self.patient,
            task_date=date_future,
            task_type=core_choices.PlanItemCategory.QUESTIONNAIRE,
            title="问卷提醒",
            status=core_choices.TaskStatus.PENDING,
        )
        DailyTask.objects.create(
            patient=self.patient,
            task_date=date_future,
            task_type=core_choices.PlanItemCategory.CHECKUP,
            title="复查提醒",
            status=core_choices.TaskStatus.PENDING,
        )
        DailyTask.objects.create(
            patient=self.patient,
            task_date=date_old,
            task_type=core_choices.PlanItemCategory.QUESTIONNAIRE,
            title="问卷提醒",
            status=core_choices.TaskStatus.PENDING,
        )
        DailyTask.objects.create(
            patient=self.patient,
            task_date=date_old,
            task_type=core_choices.PlanItemCategory.CHECKUP,
            title="复查提醒",
            status=core_choices.TaskStatus.COMPLETED,
        )

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

        sections = {
            section["key"]: section
            for section in response.context["treatment_course_sections"]
        }
        self.assertEqual(
            [section["key"] for section in response.context["treatment_course_sections"]],
            ["in_progress", "not_started", "ended"],
        )
        self.assertTrue(sections["in_progress"]["default_open"])
        self.assertFalse(sections["not_started"]["default_open"])
        self.assertFalse(sections["ended"]["default_open"])

        current_course = sections["in_progress"]["courses"][0]
        history_course = sections["ended"]["courses"][0]
        self.assertEqual(current_course["name"], cycle_current.name)
        self.assertEqual(history_course["name"], cycle_history.name)

        def find_item(course, date_str, item_type):
            return next(
                (
                    i
                    for i in course["items"]
                    if i.get("date") == date_str and i.get("type") == item_type
                ),
                None,
            )

        future_q = find_item(current_course, date_future.strftime("%Y-%m-%d"), "questionnaire")
        self.assertIsNotNone(future_q)
        self.assertEqual(future_q["status"], "not_started")

        future_c = find_item(current_course, date_future.strftime("%Y-%m-%d"), "checkup")
        self.assertIsNotNone(future_c)
        self.assertEqual(future_c["status"], "not_started")

        recent_q = find_item(current_course, date_recent.strftime("%Y-%m-%d"), "questionnaire")
        self.assertIsNotNone(recent_q)
        self.assertEqual(recent_q["status"], "incomplete")

        recent_c = find_item(current_course, date_recent.strftime("%Y-%m-%d"), "checkup")
        self.assertIsNotNone(recent_c)
        self.assertEqual(recent_c["status"], "completed")

        old_q = find_item(history_course, date_old.strftime("%Y-%m-%d"), "questionnaire")
        self.assertIsNotNone(old_q)
        self.assertEqual(old_q["status"], "terminated")

    def test_treatment_course_sections_classify_and_sort_for_patient_usage(self):
        self.client.force_login(self.user)
        today = timezone.localdate()

        cycle_specs = (
            (
                "今日开始疗程",
                today,
                today + datetime.timedelta(days=20),
                core_choices.TreatmentCycleStatus.IN_PROGRESS,
            ),
            (
                "当前较早疗程",
                today - datetime.timedelta(days=10),
                today + datetime.timedelta(days=10),
                core_choices.TreatmentCycleStatus.IN_PROGRESS,
            ),
            (
                "当前较新疗程",
                today - datetime.timedelta(days=2),
                today + datetime.timedelta(days=18),
                core_choices.TreatmentCycleStatus.IN_PROGRESS,
            ),
            (
                "今日结束疗程",
                today - datetime.timedelta(days=20),
                today,
                core_choices.TreatmentCycleStatus.IN_PROGRESS,
            ),
            (
                "稍后开始疗程",
                today + datetime.timedelta(days=5),
                today + datetime.timedelta(days=25),
                core_choices.TreatmentCycleStatus.IN_PROGRESS,
            ),
            (
                "更晚开始疗程",
                today + datetime.timedelta(days=20),
                today + datetime.timedelta(days=40),
                core_choices.TreatmentCycleStatus.IN_PROGRESS,
            ),
            (
                "最近结束疗程",
                today - datetime.timedelta(days=30),
                today - datetime.timedelta(days=2),
                core_choices.TreatmentCycleStatus.COMPLETED,
            ),
            (
                "自然结束疗程",
                today - datetime.timedelta(days=60),
                today - datetime.timedelta(days=20),
                core_choices.TreatmentCycleStatus.IN_PROGRESS,
            ),
            (
                "已终止疗程",
                today - datetime.timedelta(days=15),
                today + datetime.timedelta(days=5),
                core_choices.TreatmentCycleStatus.TERMINATED,
            ),
        )
        for name, start_date, end_date, status in cycle_specs:
            TreatmentCycle.objects.create(
                patient=self.patient,
                name=name,
                start_date=start_date,
                end_date=end_date,
                cycle_days=(end_date - start_date).days + 1,
                status=status,
            )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        sections = {
            section["key"]: section
            for section in response.context["treatment_course_sections"]
        }
        self.assertEqual(
            [course["name"] for course in sections["in_progress"]["courses"]],
            ["今日开始疗程", "当前较新疗程", "当前较早疗程", "今日结束疗程"],
        )
        self.assertEqual(
            [course["name"] for course in sections["not_started"]["courses"]],
            ["稍后开始疗程", "更晚开始疗程"],
        )
        self.assertEqual(
            [course["name"] for course in sections["ended"]["courses"]],
            ["已终止疗程", "最近结束疗程", "自然结束疗程"],
        )
        self.assertEqual(sections["ended"]["courses"][0]["status_text"], "已终止")
        self.assertEqual(sections["in_progress"]["count"], 4)
        self.assertEqual(sections["not_started"]["count"], 2)
        self.assertEqual(sections["ended"]["count"], 3)

    def test_treatment_course_sections_render_empty_states_and_stay_closed(self):
        self.client.force_login(self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        sections = response.context["treatment_course_sections"]
        self.assertEqual([section["count"] for section in sections], [0, 0, 0])
        self.assertFalse(any(section["default_open"] for section in sections))
        self.assertContains(response, "暂无进行中疗程")
        self.assertContains(response, "暂无未开始疗程")
        self.assertContains(response, "暂无已结束疗程")

    @patch(
        "web_patient.services.management_plan._get_all_treatment_cycles",
        side_effect=RuntimeError("query failed"),
    )
    def test_treatment_course_query_failure_is_logged_and_returns_empty_sections(
        self, mock_get_cycles
    ):
        self.client.force_login(self.user)

        with self.assertLogs("web_patient.services.management_plan", level="ERROR"):
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [section["count"] for section in response.context["treatment_course_sections"]],
            [0, 0, 0],
        )
        mock_get_cycles.assert_called_once_with(self.patient)
