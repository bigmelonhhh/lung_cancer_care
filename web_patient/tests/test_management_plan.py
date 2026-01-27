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
    @patch('web_patient.views.plan.HealthMetricService.query_last_metric')
    def test_management_plan_context(self, mock_query_metric, mock_get_plan):
        # 1. Mock Plan Data (In Plan)
        mock_get_plan.return_value = [
            {"task_type": "MEDICATION", "title": "按时用药", "status": 0}, # Incomplete
            {"task_type": "MONITORING", "title": "测量体温", "status": 0},
            {"task_type": "MONITORING", "title": "测量血压", "status": 0},
        ]

        # 2. Mock Metric Data (Some data exists)
        mock_query_metric.return_value = {
            MetricType.BODY_TEMPERATURE: {
                "value_display": "36.5",
                "measured_at": timezone.now()
            },
            # BP missing (Incomplete)
            # SpO2 not in plan (Should be empty status)
        }

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
    @patch('web_patient.views.plan.HealthMetricService.query_last_metric')
    def test_management_plan_view_logic(self, mock_query_metric, mock_get_plan):
        self.client.force_login(self.user)
        
        # Scenario 1: Medication In Plan, Incomplete
        # Scenario 2: Temp In Plan, Completed
        # Scenario 3: BP In Plan, Incomplete
        # Scenario 4: SpO2 Not In Plan
        
        mock_get_plan.return_value = [
            {"task_type": "MEDICATION", "title": "按时用药", "status": 0},
            {"task_type": "MONITORING", "title": "测量体温", "status": 1}, # Backend says completed, but we check data too?
                                                                        # Requirement says: "If indicator in plan... Data entered: completed"
            {"task_type": "MONITORING", "title": "测量血压", "status": 0},
        ]
        
        mock_query_metric.return_value = {
            MetricType.BODY_TEMPERATURE: {
                "value_display": "36.5",
                "measured_at": timezone.now()
            },
            MetricType.BLOOD_PRESSURE: None # No data
        }
        
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
        # Temp: In plan + Data = Completed
        temp_task = next((t for t in monitoring_plan if t['title'] == '测量体温'), None)
        self.assertIsNotNone(temp_task)
        self.assertEqual(temp_task['status'], 'completed')
        
        # BP: In plan + No Data = Incomplete
        bp_task = next((t for t in monitoring_plan if t['title'] == '测量血压/心率'), None)
        self.assertIsNotNone(bp_task)
        self.assertEqual(bp_task['status'], 'incomplete')
        
        # SpO2: Not in plan = Empty status
        spo2_task = next((t for t in monitoring_plan if t['title'] == '测量血氧'), None)
        self.assertIsNotNone(spo2_task)
        self.assertEqual(spo2_task['status'], '')
        self.assertEqual(spo2_task['status_text'], '今日无计划')

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

        courses = response.context["treatment_courses"]
        self.assertEqual(len(courses), 2)
        self.assertEqual(courses[0]["name"], cycle_current.name)
        self.assertTrue(courses[0]["is_current"])
        self.assertEqual(courses[1]["name"], cycle_history.name)
        self.assertFalse(courses[1]["is_current"])

        def find_item(course, date_str, item_type):
            return next(
                (
                    i
                    for i in course["items"]
                    if i.get("date") == date_str and i.get("type") == item_type
                ),
                None,
            )

        future_q = find_item(courses[0], date_future.strftime("%Y-%m-%d"), "questionnaire")
        self.assertIsNotNone(future_q)
        self.assertEqual(future_q["status"], "not_started")

        future_c = find_item(courses[0], date_future.strftime("%Y-%m-%d"), "checkup")
        self.assertIsNotNone(future_c)
        self.assertEqual(future_c["status"], "not_started")

        recent_q = find_item(courses[0], date_recent.strftime("%Y-%m-%d"), "questionnaire")
        self.assertIsNotNone(recent_q)
        self.assertEqual(recent_q["status"], "incomplete")

        recent_c = find_item(courses[0], date_recent.strftime("%Y-%m-%d"), "checkup")
        self.assertIsNotNone(recent_c)
        self.assertEqual(recent_c["status"], "completed")

        old_q = find_item(courses[1], date_old.strftime("%Y-%m-%d"), "questionnaire")
        self.assertIsNotNone(old_q)
        self.assertEqual(old_q["status"], "terminated")
