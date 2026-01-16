from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from django.urls import reverse
from unittest.mock import MagicMock, patch
from users.models import DoctorProfile, PatientProfile
from web_doctor.views.workspace import enrich_patients_with_counts

User = get_user_model()

class PatientListCountsTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        # Create a doctor user
        self.user = User.objects.create_user(
            username='doc', 
            password='password', 
            user_type=2,
            phone="13900139000"
        ) 
        self.doctor_profile = DoctorProfile.objects.create(user=self.user, name="Dr. Test")
        self.user.doctor_profile = self.doctor_profile
        self.user.save()
        
        # Create a patient
        self.patient_user = User.objects.create_user(
            username='pat', 
            user_type=1,
            phone="13800138000",
            wx_openid="test_openid_123"
        )
        self.patient = PatientProfile.objects.create(
            user=self.patient_user,
            name="Patient Test",
            phone="13800138000",
            doctor=self.doctor_profile
        )

    @patch('web_doctor.views.workspace.TodoListService')
    @patch('web_doctor.views.workspace.ChatService')
    def test_enrich_patients_counts_logic(self, MockChatService, MockTodoListService):
        """测试数据获取逻辑：包括 <99, =99, >99 及 0 的情况"""
        mock_todo_service = MockTodoListService
        mock_chat_service_instance = MockChatService.return_value
        
        # Scenario 1: Normal counts (< 99)
        mock_page = MagicMock()
        mock_page.paginator.count = 50
        mock_todo_service.get_todo_page.return_value = mock_page
        
        mock_chat_service_instance.get_unread_count.return_value = 10
        mock_chat_service_instance.get_or_create_patient_conversation.return_value = MagicMock()
        
        patients_qs = [self.patient]
        enriched = enrich_patients_with_counts(self.user, patients_qs)
        
        self.assertEqual(enriched[0].todo_count, 50)
        self.assertEqual(enriched[0].consult_count, 10)
        
        # Scenario 2: High counts (> 99)
        mock_page.paginator.count = 150
        mock_chat_service_instance.get_unread_count.return_value = 100
        
        enriched = enrich_patients_with_counts(self.user, patients_qs)
        self.assertEqual(enriched[0].todo_count, 150)
        self.assertEqual(enriched[0].consult_count, 100)
        
        # Scenario 3: Zero counts
        mock_page.paginator.count = 0
        mock_chat_service_instance.get_unread_count.return_value = 0
        
        enriched = enrich_patients_with_counts(self.user, patients_qs)
        self.assertEqual(enriched[0].todo_count, 0)
        self.assertEqual(enriched[0].consult_count, 0)
        
        # Scenario 4: Boundary (= 99)
        mock_page.paginator.count = 99
        mock_chat_service_instance.get_unread_count.return_value = 99
        
        enriched = enrich_patients_with_counts(self.user, patients_qs)
        self.assertEqual(enriched[0].todo_count, 99)
        self.assertEqual(enriched[0].consult_count, 99)

    @patch('web_doctor.views.workspace.TodoListService')
    @patch('web_doctor.views.workspace.ChatService')
    @patch('web_doctor.views.workspace.logger.error')
    def test_enrich_patients_exception_handling(self, mock_logger, MockChatService, MockTodoListService):
        """测试接口异常时的容错处理"""
        # Mock exceptions
        MockTodoListService.get_todo_page.side_effect = Exception("Todo Error")
        MockChatService.return_value.get_unread_count.side_effect = Exception("Chat Error")
        
        patients_qs = [self.patient]
        enriched = enrich_patients_with_counts(self.user, patients_qs)
        
        # Should default to 0 on error
        self.assertEqual(enriched[0].todo_count, 0)
        self.assertEqual(enriched[0].consult_count, 0)

    @patch('web_doctor.views.workspace.enrich_patients_with_counts')
    def test_view_template_display_logic(self, mock_enrich):
        """测试模板显示逻辑：是否正确显示 '99+' 或具体数值"""
        self.client.force_login(self.user)
        url = reverse('web_doctor:doctor_workspace_patient_list')
        
        # Case 1: > 99 (Should show 99+)
        self.patient.todo_count = 100
        self.patient.consult_count = 100
        mock_enrich.return_value = [self.patient]
        
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        
        # Check for (99+)
        self.assertIn('(99+)', content)
        # Should NOT show (100)
        self.assertNotIn('(100)', content)
        
        # Case 2: < 99 (Should show number)
        self.patient.todo_count = 50
        self.patient.consult_count = 88
        mock_enrich.return_value = [self.patient]
        
        response = self.client.get(url)
        content = response.content.decode('utf-8')
        
        self.assertIn('(50)', content)
        self.assertIn('(88)', content)
        self.assertNotIn('(99+)', content)
        
        # Case 3: = 99 (Should show 99)
        self.patient.todo_count = 99
        self.patient.consult_count = 99
        mock_enrich.return_value = [self.patient]
        
        response = self.client.get(url)
        content = response.content.decode('utf-8')
        
        self.assertIn('(99)', content)
        self.assertNotIn('(99+)', content)
        
        # Case 4: Zero (Should show 0)
        self.patient.todo_count = 0
        self.patient.consult_count = 0
        mock_enrich.return_value = [self.patient]
        
        response = self.client.get(url)
        content = response.content.decode('utf-8')
        
        self.assertIn('(0)', content)

    @patch('web_doctor.views.workspace.enrich_patients_with_counts')
    def test_polling_trigger_exists(self, mock_enrich):
        """测试是否包含轮询触发器"""
        # Mock return value to avoid ChatService error
        self.patient.todo_count = 0
        self.patient.consult_count = 0
        mock_enrich.return_value = [self.patient]

        self.client.force_login(self.user)
        url = reverse('web_doctor:doctor_workspace_patient_list')
        response = self.client.get(url)
        content = response.content.decode('utf-8')
        
        # Check for hx-trigger="every 180s"
        self.assertIn('hx-trigger="every 180s"', content)
        self.assertIn('hx-get="/doctor/workspace/patient-list/"', content) # Or check resolved url
