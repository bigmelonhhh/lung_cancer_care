import json
import logging
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from users.models import PatientProfile
from chat.models import Conversation, Message, PatientStudioAssignment

from django.utils import timezone
from users.choices import UserType
from users.models import PatientProfile, DoctorProfile, DoctorStudio

User = get_user_model()

class ChatApiTests(TestCase):
    def setUp(self):
        # Create user and patient
        self.user = User.objects.create_user(
            username='patient_test', 
            password='password',
            wx_openid='test_openid_123',
            user_type=UserType.PATIENT
        )
        self.patient = PatientProfile.objects.create(user=self.user, name='Test Patient', phone='1234567890')
        
        # Create Doctor & Studio
        self.doctor_user = User.objects.create_user(
            username='doctor_test', 
            password='password', 
            user_type=UserType.DOCTOR,
            phone='13800000000'
        )
        self.doctor_profile = DoctorProfile.objects.create(user=self.doctor_user, name='Dr Test')
        self.studio = DoctorStudio.objects.create(name='Test Studio', owner_doctor=self.doctor_profile)
        self.doctor_profile.studio = self.studio
        self.doctor_profile.save()
        
        # Assign patient to studio
        PatientStudioAssignment.objects.create(
            patient=self.patient,
            studio=self.studio,
            start_at=timezone.now()
        )
        
        self.client = Client()
        self.client.login(username='patient_test', password='password')
        
        # URL endpoints
        self.list_url = reverse('web_patient:chat_api_list_messages')
        self.send_url = reverse('web_patient:chat_api_send_text')
        
    def test_list_messages_empty(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(len(data['messages']), 0)
        
    def test_send_and_list_messages(self):
        # Send message
        content = "Hello Doctor"
        response = self.client.post(
            self.send_url,
            json.dumps({'content': content}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("created_at_display", payload["message"])
        
        # Check DB
        self.assertEqual(Message.objects.count(), 1)
        msg = Message.objects.first()
        self.assertEqual(msg.text_content, content)
        self.assertEqual(msg.sender, self.user)
        self.assertTrue(timezone.is_aware(msg.created_at))
        
        # List messages
        response = self.client.get(self.list_url)
        data = response.json()
        self.assertEqual(len(data['messages']), 1)
        self.assertEqual(data['messages'][0]['text_content'], content)
        self.assertIn("created_at_display", data["messages"][0])

    def test_send_invalid_content(self):
         # Test sending empty content (assuming service/view validation)
         # If service allows empty, this test might fail. 
         # But usually chat services require content.
         # Let's check with a None content which usually fails validation.
         logging.disable(logging.CRITICAL)
         try:
             response = self.client.post(
                self.send_url,
                json.dumps({'content': None}), 
                content_type='application/json'
            )
             self.assertNotEqual(response.status_code, 200)
         finally:
             logging.disable(logging.NOTSET)
