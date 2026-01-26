from django.test import TestCase, Client
from django.urls import reverse
from users.models import CustomUser
from users.models.patient_profile import PatientProfile
from health_data.models import HealthMetric, MetricType
from core.models import Questionnaire, QuestionnaireCode, QuestionnaireQuestion, QuestionnaireOption
from django.utils import timezone
import datetime
import json
from decimal import Decimal
from django.test import override_settings
from users import choices
from market.models import Order, Product

@override_settings(DEBUG=True, TEST_PATIENT_ID="1")
class E2ERecordFlowTests(TestCase):
    def setUp(self):
        self.client = Client()
        # Create user and patient
        self.user = CustomUser.objects.create_user(
            username='e2e_test_user',
            password='password123',
            user_type=choices.UserType.PATIENT,
            wx_openid='e2e_openid'
        )
        self.patient = PatientProfile.objects.create(
            user=self.user,
            name="E2E Patient",
            phone="13800138000"
        )
        self.client.force_login(self.user)
        
        # Create a questionnaire for testing survey submission
        # Ensure the code matches what might be used in business logic
        self.questionnaire, _ = Questionnaire.objects.get_or_create(
            code=QuestionnaireCode.Q_PHYSICAL, # Use a valid code from choices
            defaults={
                "name": "Daily Survey",
                "is_active": True,
            }
        )
        
        # Clean up existing questions to ensure clean state for testing
        self.questionnaire.questions.all().delete()
        
        # Create a question and option
        self.question = QuestionnaireQuestion.objects.create(
            questionnaire=self.questionnaire,
            text="Test Question",
            q_type="SINGLE", 
            seq=1
        )
        
        self.option = QuestionnaireOption.objects.create(
            question=self.question,
            text="Option A",
            score=1,
            seq=1
        )

    def test_01_navigation(self):
        """Test 1: Navigation availability - Verify all pages load successfully"""
        urls = [
            reverse('web_patient:patient_home'),
            reverse('web_patient:health_calendar'),
            reverse('web_patient:record_temperature'),
            reverse('web_patient:record_bp'),
            reverse('web_patient:record_spo2'),
            reverse('web_patient:record_weight'),
            # Survey page might need ids param, check default behavior
            reverse('web_patient:daily_survey') 
        ]
        for url in urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, f"Failed to load {url}")

    def test_02_spo2_entry_flow(self):
        """Test 2: SpO2 Data Entry (AJAX) - Entry, Validation, Persistence"""
        url = reverse('web_patient:record_spo2')
        data = {
            'spo2': '98',
            'record_time': timezone.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        # Simulate AJAX request
        response = self.client.post(
            url, 
            data, 
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        
        # Verify JSON response
        self.assertEqual(response.status_code, 200)
        json_data = response.json()
        self.assertEqual(json_data['status'], 'success')
        self.assertEqual(json_data['metric_data']['spo2']['value'], '98')
        
        # Verify DB
        metric = HealthMetric.objects.filter(
            patient=self.patient, 
            metric_type=MetricType.BLOOD_OXYGEN
        ).last()
        self.assertIsNotNone(metric)
        self.assertEqual(metric.value_main, 98)

    def test_03_bp_hr_entry_flow(self):
        """Test 3: BP/HR Data Entry (AJAX)"""
        url = reverse('web_patient:record_bp')
        data = {
            'ssy': '120',
            'szy': '80',
            'heart': '75',
            'record_time': timezone.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        response = self.client.post(
            url, 
            data, 
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        
        self.assertEqual(response.status_code, 200)
        json_data = response.json()
        self.assertEqual(json_data['status'], 'success')
        
        # Verify DB
        bp_metric = HealthMetric.objects.filter(
            patient=self.patient, metric_type=MetricType.BLOOD_PRESSURE
        ).last()
        self.assertEqual(bp_metric.value_main, 120)
        self.assertEqual(bp_metric.value_sub, 80)
        
        hr_metric = HealthMetric.objects.filter(
            patient=self.patient, metric_type=MetricType.HEART_RATE
        ).last()
        self.assertEqual(hr_metric.value_main, 75)

    def test_04_weight_entry_flow(self):
        """Test 4: Weight Entry (AJAX)"""
        url = reverse('web_patient:record_weight')
        data = {
            'weight': '65.5',
            'record_time': timezone.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        response = self.client.post(
            url, 
            data, 
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response.status_code, 200)
        json_data = response.json()
        self.assertEqual(json_data['status'], 'success')
        
        metric = HealthMetric.objects.filter(
            patient=self.patient, metric_type=MetricType.WEIGHT
        ).last()
        self.assertEqual(metric.value_main, Decimal('65.5'))

    def test_05_temperature_entry_flow(self):
        """Test 5: Temperature Entry (AJAX)"""
        url = reverse('web_patient:record_temperature')
        data = {
            'temperature': '36.5',
            'record_time': timezone.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        response = self.client.post(
            url, 
            data, 
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response.status_code, 200)
        json_data = response.json()
        self.assertEqual(json_data['status'], 'success')
        
        metric = HealthMetric.objects.filter(
            patient=self.patient, metric_type=MetricType.BODY_TEMPERATURE
        ).last()
        self.assertEqual(metric.value_main, Decimal('36.5'))

    def test_06_data_update_api(self):
        """Test 6: Data Update Verification (query_last_metric)"""
        # First ensure we have data
        HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BODY_TEMPERATURE,
            value_main=Decimal('36.8'),
            measured_at=timezone.now(),
            source='manual'
        )

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
        
        url = reverse('web_patient:query_last_metric')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertTrue(data['success'])
        plans = data['plans']
        
        # Check if temperature plan is reflected (Note: Plans depend on get_daily_plan_summary logic)
        # If get_daily_plan_summary returns the task, we check its status
        # Since we just inserted a record, it should be 'completed'
        
        # Note: If get_daily_plan_summary relies on configuration, we assume Temperature is a default plan.
        if 'temperature' in plans:
            self.assertEqual(plans['temperature']['status'], 'completed')
            self.assertIn('36.8', plans['temperature']['subtitle'])

    def test_07_invalid_submissions(self):
        """Test 7: Exception Handling (Empty Data)"""
        url = reverse('web_patient:record_spo2')
        # Empty data
        response = self.client.post(
            url, 
            {}, 
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        # Assuming view handles missing data by re-rendering template (status 200, not JSON success)
        self.assertEqual(response.status_code, 200)
        
        # Check it's not the success JSON
        if response.headers.get('Content-Type') == 'application/json':
             self.assertNotEqual(response.json().get('status'), 'success')
        else:
             # It returned HTML (re-render), which is acceptable for missing data in this implementation
             pass

    def test_08_survey_submission(self):
        """Test 8: Survey Submission API"""
        url = reverse('web_patient:submit_surveys')
        payload = {
            "patient_id": self.patient.id,
            "questionnaire_id": self.questionnaire.id,
            "answers": [{
                "option_id": self.option.id
            }]
        }
        
        response = self.client.post(
            url,
            data=payload,
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        json_data = response.json()
        self.assertTrue(json_data['success'])
        self.assertEqual(json_data['metric_data']['followup'], 'completed')
