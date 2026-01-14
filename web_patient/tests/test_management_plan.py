from django.test import TestCase, RequestFactory
from django.urls import reverse
from unittest.mock import patch, MagicMock
from web_patient.views.plan import management_plan
from users.models import PatientProfile, CustomUser
from health_data.models import MetricType
from django.utils import timezone
import datetime

class ManagementPlanViewTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = CustomUser.objects.create_user(
            username='testpatient', 
            password='password',
            wx_openid='test_openid_123'
        )
        self.patient = PatientProfile.objects.create(user=self.user, name="Test Patient")
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
        bp_task = next((t for t in monitoring_plan if t['title'] == '测量血压'), None)
        self.assertIsNotNone(bp_task)
        self.assertEqual(bp_task['status'], 'incomplete')
        
        # SpO2: Not in plan = Empty status
        spo2_task = next((t for t in monitoring_plan if t['title'] == '测量血氧'), None)
        self.assertIsNotNone(spo2_task)
        self.assertEqual(spo2_task['status'], '')
        self.assertEqual(spo2_task['status_text'], '今日无计划')

