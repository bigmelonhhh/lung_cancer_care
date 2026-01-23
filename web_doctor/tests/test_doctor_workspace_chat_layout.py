from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from unittest.mock import patch

from users.models import DoctorProfile

User = get_user_model()


class DoctorWorkspaceChatLayoutTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="doc_layout",
            password="password",
            user_type=2,
            phone="13900139001",
        )
        DoctorProfile.objects.create(user=self.user, name="Dr. Layout")

    @patch("web_doctor.views.workspace.enrich_patients_with_counts", return_value=[])
    def test_doctor_workspace_contains_chat_and_todo_regions(self, _mock_enrich):
        self.client.force_login(self.user)
        url = reverse("web_doctor:doctor_workspace")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        content = response.content.decode("utf-8")
        self.assertIn('id="patient-todo-list"', content)
        self.assertIn('id="chat-messages-container"', content)
        self.assertIn("doctor-chat-scroll", content)
        self.assertIn("doctor-chat-input", content)
        self.assertIn('doctor-chat-input" x-show="canChat"', content)
        self.assertNotIn("clamp(120px, 16vh, 360px)", content)
        self.assertNotIn("--doctor-chat-input-height", content)
        self.assertIn("this.canChat ? 120 : 0", content)
