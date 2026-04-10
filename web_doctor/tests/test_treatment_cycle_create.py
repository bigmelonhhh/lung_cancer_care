from datetime import date, timedelta
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from core.models import TreatmentCycle
from users.choices import UserType
from users.models import CustomUser, DoctorProfile, PatientProfile
from web_doctor.views import workspace


class TreatmentCycleCreateViewTests(TestCase):
    def setUp(self):
        self.doctor_user = CustomUser.objects.create_user(
            username="doctor_cycle_create",
            password="password123",
            user_type=UserType.DOCTOR,
            phone="13900008880",
        )
        self.doctor_profile = DoctorProfile.objects.create(user=self.doctor_user, name="张医生")

        patient_user = CustomUser.objects.create_user(
            username="patient_cycle_create",
            password="password123",
            user_type=UserType.PATIENT,
            phone="13800008880",
            wx_openid="openid_cycle_create",
        )
        self.patient = PatientProfile.objects.create(
            user=patient_user,
            doctor=self.doctor_profile,
            name="患者D",
            phone="13800008880",
            is_active=True,
        )
        self.client.login(username="doctor_cycle_create", password="password123")
        self.create_url = reverse("web_doctor:patient_treatment_cycle_create", args=[self.patient.id])
        self.settings_url = reverse("web_doctor:patient_workspace_section", args=[self.patient.id, "settings"])

    def _patch_settings_dependencies(self):
        patches = [
            patch("web_doctor.views.workspace.get_active_medication_library", return_value=[]),
            patch("web_doctor.views.workspace.PlanItemService.get_cycle_plan_view", return_value={}),
            patch("web_doctor.views.workspace.MedicalHistoryService.get_last_medical_history", return_value=None),
            patch("web_doctor.views.workspace.get_active_treatment_cycle", return_value=None),
            patch("web_doctor.views.workspace.PatientService"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        patient_service_mock = workspace.PatientService.return_value
        patient_service_mock.get_patient_family_members.return_value = []

    def test_settings_page_renders_custom_cycle_fields(self):
        self._patch_settings_dependencies()

        response = self.client.get(self.settings_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="cycle_days_mode"')
        self.assertContains(response, 'option value="custom"')
        self.assertContains(response, 'name="cycle_days_custom"')
        

    def test_create_cycle_with_preset_28_days_succeeds(self):
        self._patch_settings_dependencies()
        start_date = date(2026, 4, 9)

        response = self.client.post(
            self.create_url,
            {
                "name": "28天疗程",
                "start_date": start_date.isoformat(),
                "cycle_days_mode": "28",
            },
        )

        self.assertEqual(response.status_code, 200)
        cycle = TreatmentCycle.objects.get(name="28天疗程")
        self.assertEqual(cycle.cycle_days, 28)
        self.assertEqual(cycle.end_date, start_date + timedelta(days=27))

    def test_create_cycle_with_custom_days_succeeds(self):
        self._patch_settings_dependencies()
        start_date = date(2026, 4, 9)

        response = self.client.post(
            self.create_url,
            {
                "name": "自定义疗程",
                "start_date": start_date.isoformat(),
                "cycle_days_mode": "custom",
                "cycle_days_custom": "15",
            },
        )

        self.assertEqual(response.status_code, 200)
        cycle = TreatmentCycle.objects.get(name="自定义疗程")
        self.assertEqual(cycle.cycle_days, 15)
        self.assertEqual(cycle.end_date, start_date + timedelta(days=14))

    def test_create_cycle_with_empty_custom_days_shows_error_and_preserves_selection(self):
        self._patch_settings_dependencies()

        response = self.client.post(
            self.create_url,
            {
                "name": "空自定义疗程",
                "start_date": "2026-04-09",
                "cycle_days_mode": "custom",
                "cycle_days_custom": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(TreatmentCycle.objects.filter(name="空自定义疗程").exists())
        self.assertContains(response, "请输入 2-60 天的疗程天数。")

        html = response.content.decode("utf-8")
        self.assertIn('option value="custom" selected', html)
        self.assertIn('name="cycle_days_custom"', html)

    def test_create_cycle_with_invalid_custom_days_preserves_raw_value(self):
        self._patch_settings_dependencies()

        response = self.client.post(
            self.create_url,
            {
                "name": "超范围疗程",
                "start_date": "2026-04-09",
                "cycle_days_mode": "custom",
                "cycle_days_custom": "61",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(TreatmentCycle.objects.filter(name="超范围疗程").exists())
        self.assertContains(response, "周期天数必须在 2-60 天之间。")

        html = response.content.decode("utf-8")
        self.assertIn('option value="custom" selected', html)
        self.assertIn('value="61"', html)

    def test_create_cycle_with_non_integer_custom_days_shows_error(self):
        self._patch_settings_dependencies()

        response = self.client.post(
            self.create_url,
            {
                "name": "非整数疗程",
                "start_date": "2026-04-09",
                "cycle_days_mode": "custom",
                "cycle_days_custom": "abc",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(TreatmentCycle.objects.filter(name="非整数疗程").exists())
        self.assertContains(response, "请输入 2-60 天的疗程天数。")

        html = response.content.decode("utf-8")
        self.assertIn('option value="custom" selected', html)
        self.assertIn('value="abc"', html)

    def test_create_cycle_legacy_cycle_days_submission_still_works(self):
        self._patch_settings_dependencies()
        start_date = date(2026, 4, 9)

        response = self.client.post(
            self.create_url,
            {
                "name": "旧版提交疗程",
                "start_date": start_date.isoformat(),
                "cycle_days": "15",
            },
        )

        self.assertEqual(response.status_code, 200)
        cycle = TreatmentCycle.objects.get(name="旧版提交疗程")
        self.assertEqual(cycle.cycle_days, 15)
        self.assertEqual(cycle.end_date, start_date + timedelta(days=14))
