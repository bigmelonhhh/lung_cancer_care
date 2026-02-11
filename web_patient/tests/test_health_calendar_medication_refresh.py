from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from users.models import CustomUser, PatientProfile, PatientRelation
from users import choices
from unittest.mock import patch
from core.models import TreatmentCycle
from core.models import choices as core_choices

class HealthCalendarMedicationRefreshTests(TestCase):
  def setUp(self):
    self.user = CustomUser.objects.create_user(
      username="calendar_user",
      password="password",
      user_type=choices.UserType.PATIENT,
      wx_openid="open_calendar_user",
    )
    self.patient = PatientProfile.objects.create(
      user=self.user,
      name="日历患者",
      phone="13800000020",
    )
    self.client.force_login(self.user)
    self.calendar_url = reverse("web_patient:health_calendar")
    self.submit_url = reverse("web_patient:submit_medication")
    self.today = timezone.localdate().strftime("%Y-%m-%d")
    today = timezone.localdate()
    TreatmentCycle.objects.create(
      patient=self.patient,
      name="进行中疗程",
      start_date=today,
      end_date=today,
      status=core_choices.TreatmentCycleStatus.IN_PROGRESS,
    )

  @patch("web_patient.views.health_calendar.get_daily_plan_summary")
  def test_patient_medication_refresh_to_completed(self, mock_summary):
    mock_summary.return_value = [{"title": "用药提醒", "status": "pending", "task_type": "medication"}]
    resp = self.client.get(f"{self.calendar_url}?date={self.today}&ajax=1")
    self.assertEqual(resp.status_code, 200)
    self.assertIn("去服药", resp.content.decode("utf-8"))
    resp = self.client.post(self.submit_url, {"patient_id": self.patient.id, "selected_date": self.today})
    self.assertEqual(resp.status_code, 200)
    data = resp.json()
    self.assertTrue(data["success"])
    resp = self.client.get(f"{self.calendar_url}?date={self.today}&ajax=1")
    html = resp.content.decode("utf-8")
    self.assertIn("已服药", html)
    self.assertIn("w-8 h-8 rounded-full bg-emerald-100", html)

  @patch("web_patient.views.health_calendar.get_daily_plan_summary")
  def test_family_account_medication_refresh_to_completed(self, mock_summary):
    mock_summary.return_value = [{"title": "用药提醒", "status": "pending", "task_type": "medication"}]
    family_user = CustomUser.objects.create_user(
      username="family_user",
      password="password",
      user_type=choices.UserType.PATIENT,
      wx_openid="open_family_user",
    )
    PatientRelation.objects.create(patient=self.patient, user=family_user, is_active=True)
    self.client.force_login(family_user)
    resp = self.client.get(f"{self.calendar_url}?date={self.today}&ajax=1")
    self.assertEqual(resp.status_code, 200)
    resp = self.client.post(self.submit_url, {"patient_id": self.patient.id, "selected_date": self.today})
    self.assertEqual(resp.status_code, 200)
    resp = self.client.get(f"{self.calendar_url}?date={self.today}&ajax=1")
    html = resp.content.decode("utf-8")
    self.assertIn("已服药", html)
    self.assertIn("w-8 h-8 rounded-full bg-emerald-100", html)
