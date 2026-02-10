from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import TreatmentCycle
from core.models import choices as core_choices
from users import choices as user_choices
from users.models import CustomUser, PatientProfile


class HealthCalendarActionEnabledTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username="calendar_action_user",
            password="password",
            user_type=user_choices.UserType.PATIENT,
            wx_openid="openid_calendar_action_user",
        )
        self.patient = PatientProfile.objects.create(
            user=self.user,
            name="日历患者",
            phone="13800000031",
        )
        self.client.force_login(self.user)
        self.calendar_url = reverse("web_patient:health_calendar")

    @patch("web_patient.views.health_calendar.get_daily_plan_summary")
    def test_outside_active_cycle_hide_buttons_show_check(self, mock_summary):
        today = timezone.localdate()
        TreatmentCycle.objects.create(
            patient=self.patient,
            name="进行中疗程",
            start_date=today,
            end_date=today,
            status=core_choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        target_date = today - timedelta(days=7)
        mock_summary.return_value = [
            {"title": "用药提醒", "status": 0, "task_type": core_choices.PlanItemCategory.MEDICATION},
        ]
        resp = self.client.get(f"{self.calendar_url}?date={target_date.strftime('%Y-%m-%d')}&ajax=1")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode("utf-8")
        self.assertNotIn("去服药", html)
        self.assertIn("w-8 h-8 rounded-full bg-slate-200", html)

