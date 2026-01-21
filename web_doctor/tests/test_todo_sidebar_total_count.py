from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from unittest.mock import MagicMock, patch
from users.models import DoctorProfile, PatientProfile

User = get_user_model()


class TodoSidebarTotalCountTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="doc",
            password="password",
            user_type=2,
            phone="13900139000",
        )
        self.doctor_profile = DoctorProfile.objects.create(user=self.user, name="Dr. Test")
        self.user.doctor_profile = self.doctor_profile
        self.user.save()

        self.patient_user = User.objects.create_user(
            username="pat",
            user_type=1,
            phone="13800138000",
            wx_openid="test_openid_123",
        )
        self.patient = PatientProfile.objects.create(
            user=self.patient_user,
            name="Patient Test",
            phone="13800138000",
            doctor=self.doctor_profile,
        )

    @patch("web_doctor.views.todo_workspace.TodoListService")
    def test_patient_todo_sidebar_shows_total_count(self, MockTodoListService):
        mock_page = MagicMock()
        mock_page.paginator.count = 37
        mock_page.object_list = [
            {
                "id": 1,
                "patient_id": self.patient.id,
                "patient_name": self.patient.name,
                "event_title": "T1",
                "event_content": "C1",
                "event_time": "2026-01-01 00:00",
                "status": "pending",
                "status_display": "待处理",
            }
        ] * 5
        MockTodoListService.get_todo_page.return_value = mock_page

        self.client.force_login(self.user)
        url = reverse("web_doctor:patient_todo_sidebar", args=[self.patient.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        content = response.content.decode("utf-8")
        self.assertIn('text-rose-500">(37)</span>', content)

    @patch("web_doctor.views.workspace.TodoListService")
    @patch("web_doctor.views.workspace.build_home_context", return_value={})
    def test_patient_workspace_passes_total_count_to_sidebar(self, mock_build_home_context, MockTodoListService):
        mock_page = MagicMock()
        mock_page.paginator.count = 12
        mock_page.object_list = [
            {
                "id": 1,
                "patient_id": self.patient.id,
                "patient_name": self.patient.name,
                "event_title": "T1",
                "event_content": "C1",
                "event_time": "2026-01-01 00:00",
                "status": "pending",
                "status_display": "待处理",
            }
        ] * 5
        MockTodoListService.get_todo_page.return_value = mock_page

        captured_sidebar_context = {}

        def _fake_render_to_string(template_name, context=None, request=None, **kwargs):
            nonlocal captured_sidebar_context
            if template_name == "web_doctor/partials/todo_list_sidebar.html":
                captured_sidebar_context = context or {}
            return ""

        with patch("web_doctor.views.workspace.render_to_string", side_effect=_fake_render_to_string):
            self.client.force_login(self.user)
            url = reverse("web_doctor:patient_workspace", args=[self.patient.id])
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)

        self.assertEqual(captured_sidebar_context.get("todo_total"), 12)

