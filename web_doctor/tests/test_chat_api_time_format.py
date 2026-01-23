import json
from datetime import datetime, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from chat.models import Conversation, ConversationType, Message, MessageSenderRole, PatientStudioAssignment
from users.choices import UserType
from users.models import DoctorProfile, DoctorStudio, PatientProfile

User = get_user_model()


class DoctorChatApiTimeFormatTests(TestCase):
    def setUp(self):
        self.client = Client()

        self.director_user = User.objects.create_user(
            username="director_chat_api",
            password="password",
            user_type=UserType.DOCTOR,
            phone="13800000001",
        )
        self.director_profile = DoctorProfile.objects.create(user=self.director_user, name="Dr Director")
        self.studio = DoctorStudio.objects.create(name="Time Studio", owner_doctor=self.director_profile)
        self.director_profile.studio = self.studio
        self.director_profile.save()

        self.doctor_user = User.objects.create_user(
            username="doctor_chat_api",
            password="password",
            user_type=UserType.DOCTOR,
            phone="13800000003",
        )
        self.doctor_profile = DoctorProfile.objects.create(user=self.doctor_user, name="Dr Time")
        self.doctor_profile.studio = self.studio
        self.doctor_profile.save()

        self.patient_user = User.objects.create_user(
            username="patient_chat_api",
            password="password",
            user_type=UserType.PATIENT,
            phone="13800000002",
            wx_openid="test_openid_time_1",
        )
        self.patient = PatientProfile.objects.create(
            user=self.patient_user,
            name="Test Patient",
            phone="13800000002",
            doctor=self.doctor_profile,
            is_active=True,
        )
        PatientStudioAssignment.objects.create(patient=self.patient, studio=self.studio, start_at=timezone.now())

        self.conversation = Conversation.objects.create(
            type=ConversationType.PATIENT_STUDIO,
            patient=self.patient,
            studio=self.studio,
            created_by=self.doctor_user,
        )

        self.client.force_login(self.doctor_user)

    def test_list_messages_includes_created_at_display_full_format(self):
        msg = Message.objects.create(
            conversation=self.conversation,
            sender=self.patient_user,
            sender_role_snapshot=MessageSenderRole.PATIENT,
            sender_display_name_snapshot="患者A",
            studio_name_snapshot=self.studio.name,
            text_content="hello",
        )
        fixed_utc = datetime(2026, 1, 2, 3, 4, tzinfo=dt_timezone.utc)
        Message.objects.filter(pk=msg.pk).update(created_at=fixed_utc)
        msg.refresh_from_db()
        self.assertTrue(timezone.is_aware(msg.created_at))

        url = reverse("web_doctor:chat_api_list_messages")
        response = self.client.get(url, {"conversation_id": self.conversation.id})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(len(payload["messages"]), 1)
        self.assertIn("created_at_display", payload["messages"][0])

        display = payload["messages"][0]["created_at_display"]
        self.assertRegex(display, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")

    def test_send_text_message_returns_created_at_display(self):
        url = reverse("web_doctor:chat_api_send_text")
        response = self.client.post(
            url,
            data=json.dumps({"conversation_id": self.conversation.id, "content": "hi"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("created_at_display", payload["message"])
        self.assertRegex(payload["message"]["created_at_display"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
