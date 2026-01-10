from datetime import date, datetime, timedelta
from django.test import TestCase
from django.utils import timezone
from unittest.mock import MagicMock, patch

from users.models import CustomUser, PatientProfile, DoctorStudio, DoctorProfile
from users import choices as user_choices
from chat.models import ConversationSession, ConversationType, Conversation
from web_doctor.views.management_stats import ManagementStatsView

class TestManagementStatsChatIntegration(TestCase):
    def setUp(self):
        # Create user and patient
        self.user = CustomUser.objects.create_user(
            username='testuser', 
            password='password',
            wx_openid='test_openid'
        )
        self.patient = PatientProfile.objects.create(user=self.user, name="Test Patient")
        
        # Create doctor and studio
        self.doctor_user = CustomUser.objects.create_user(
            username='doctor',
            password='password',
            user_type=user_choices.UserType.DOCTOR,
            phone="13800138000"
        )
        self.doctor_profile = DoctorProfile.objects.create(user=self.doctor_user, name="Test Doctor")
        self.studio = DoctorStudio.objects.create(name="Test Studio", owner_doctor=self.doctor_profile)
        
        # Create Conversation
        self.conversation = Conversation.objects.create(
            patient=self.patient,
            studio=self.studio,
            type=ConversationType.PATIENT_STUDIO
        )
        
        self.view = ManagementStatsView()
        
        self.start_date = date(2025, 1, 1)
        self.end_date = date(2025, 3, 31)

    def test_generate_query_stats_empty(self):
        """Test with no data"""
        stats = self.view._generate_query_stats(self.patient, self.start_date, self.end_date)
        
        self.assertEqual(stats['total_count'], 0)
        self.assertEqual(len(stats['line_chart']['xAxis']), 3) # Jan, Feb, Mar
        self.assertEqual(stats['line_chart']['series'][0]['data'], [0, 0, 0])
        self.assertEqual(len(stats['pie_chart']['series']), 0)

    def test_generate_query_stats_with_data(self):
        """Test with some conversation sessions"""
        # Create sessions
        # 1. Jan 15, 08:00 (Slot 7-10)
        ConversationSession.objects.create(
            conversation=self.conversation,
            patient=self.patient,
            conversation_type=ConversationType.PATIENT_STUDIO,
            start_at=timezone.make_aware(datetime(2025, 1, 15, 8, 0)),
            end_at=timezone.make_aware(datetime(2025, 1, 15, 8, 30)),
            message_count=5
        )
        
        # 2. Feb 10, 14:00 (Slot 13-18)
        ConversationSession.objects.create(
            conversation=self.conversation,
            patient=self.patient,
            conversation_type=ConversationType.PATIENT_STUDIO,
            start_at=timezone.make_aware(datetime(2025, 2, 10, 14, 0)),
            end_at=timezone.make_aware(datetime(2025, 2, 10, 14, 30)),
            message_count=5
        )
        
        # 3. Feb 20, 15:00 (Slot 13-18)
        ConversationSession.objects.create(
            conversation=self.conversation,
            patient=self.patient,
            conversation_type=ConversationType.PATIENT_STUDIO,
            start_at=timezone.make_aware(datetime(2025, 2, 20, 15, 0)),
            end_at=timezone.make_aware(datetime(2025, 2, 20, 15, 30)),
            message_count=5
        )

        stats = self.view._generate_query_stats(self.patient, self.start_date, self.end_date)
        
        self.assertEqual(stats['total_count'], 3)
        
        # Line chart: Jan=1, Feb=2, Mar=0
        self.assertEqual(stats['line_chart']['xAxis'], ['2025-01', '2025-02', '2025-03'])
        self.assertEqual(stats['line_chart']['series'][0]['data'], [1, 2, 0])
        
        # Pie chart: 
        # 7-10: 1
        # 13-18: 2
        series = stats['pie_chart']['series']
        self.assertEqual(len(series), 2)
        
        slot_7_10 = next((item for item in series if item['name'] == '07:00-10:00'), None)
        self.assertIsNotNone(slot_7_10)
        self.assertEqual(slot_7_10['value'], 1)
        
        slot_13_18 = next((item for item in series if item['name'] == '13:00-18:00'), None)
        self.assertIsNotNone(slot_13_18)
        self.assertEqual(slot_13_18['value'], 2)

    def test_generate_query_stats_missing_args(self):
        """Test with missing arguments"""
        stats = self.view._generate_query_stats(None, None, None)
        self.assertEqual(stats['total_count'], 0)

    @patch('chat.services.chat.ChatService.get_patient_chat_session_stats')
    def test_generate_query_stats_exception(self, mock_get_stats):
        """Test exception handling"""
        mock_get_stats.side_effect = Exception("DB Error")
        
        stats = self.view._generate_query_stats(self.patient, self.start_date, self.end_date)
        self.assertEqual(stats['total_count'], 0)
        self.assertEqual(len(stats['line_chart']['xAxis']), 0)
