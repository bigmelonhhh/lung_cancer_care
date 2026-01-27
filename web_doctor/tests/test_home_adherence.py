from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.urls import reverse

from core.models import choices
from core.service.tasks import MONITORING_ADHERENCE_ALL
from users.choices import UserType
from users.models import CustomUser, DoctorProfile, PatientProfile
from web_doctor.views.home import build_home_context


class HomeAdherenceTests(TestCase):
    def setUp(self):
        self.patient = PatientProfile.objects.create(name="Test Patient", phone="13800138009")

    @patch("web_doctor.views.home.get_paid_orders_for_patient")
    @patch("web_doctor.views.home.PatientService")
    @patch("web_doctor.views.home.MedicalHistoryService")
    @patch("web_doctor.views.home.get_active_treatment_cycle")
    @patch("web_doctor.views.home.get_active_checkup_library")
    @patch("web_doctor.views.home.get_adherence_metrics")
    def test_build_home_context_uses_real_adherence_metrics(
        self,
        mock_get_adherence_metrics,
        mock_lib,
        mock_cycle,
        mock_history,
        mock_ps,
        mock_get_orders,
    ):
        mock_ps.return_value.get_guard_days.return_value = (10, 20)
        mock_history.get_last_medical_history.return_value = None
        mock_cycle.return_value = None
        mock_lib.return_value = []

        today = date.today()
        mock_order = MagicMock()
        mock_order.start_date = today - timedelta(days=1)
        mock_order.end_date = today + timedelta(days=1)
        mock_get_orders.return_value = [mock_order]

        def _fake_metrics(*, patient_id, adherence_type, **kwargs):
            if adherence_type == choices.PlanItemCategory.MEDICATION:
                return {
                    "type": adherence_type,
                    "start_date": today - timedelta(days=7),
                    "end_date": today - timedelta(days=1),
                    "total": 10,
                    "completed": 5,
                    "rate": 0.5,
                }
            if adherence_type == MONITORING_ADHERENCE_ALL:
                return {
                    "type": adherence_type,
                    "start_date": today - timedelta(days=7),
                    "end_date": today - timedelta(days=1),
                    "total": 20,
                    "completed": 10,
                    "rate": 0.5,
                }
            raise AssertionError(f"Unexpected adherence_type: {adherence_type}")

        mock_get_adherence_metrics.side_effect = _fake_metrics

        context = build_home_context(self.patient)

        self.assertIn("medication_adherence", context)
        self.assertIn("monitoring_adherence", context)
        self.assertEqual(context["medication_adherence_display"], "50%（5/10）")
        self.assertEqual(context["monitoring_adherence_display"], "50%（10/20）")
        self.assertTrue(context["adherence_date_range"])

        mock_get_adherence_metrics.assert_any_call(
            patient_id=self.patient.id,
            adherence_type=choices.PlanItemCategory.MEDICATION,
        )
        mock_get_adherence_metrics.assert_any_call(
            patient_id=self.patient.id,
            adherence_type=MONITORING_ADHERENCE_ALL,
        )

    @patch("web_doctor.views.home.get_paid_orders_for_patient")
    @patch("web_doctor.views.home.PatientService")
    @patch("web_doctor.views.home.MedicalHistoryService")
    @patch("web_doctor.views.home.get_active_treatment_cycle")
    @patch("web_doctor.views.home.get_active_checkup_library")
    @patch("web_doctor.views.home.get_adherence_metrics")
    def test_overview_template_renders_adherence(
        self,
        mock_get_adherence_metrics,
        mock_lib,
        mock_cycle,
        mock_history,
        mock_ps,
        mock_get_orders,
    ):
        doctor_user = CustomUser.objects.create_user(
            username="doctor_adherence",
            password="password123",
            user_type=UserType.DOCTOR,
            phone="13900000009",
        )
        doctor_profile = DoctorProfile.objects.create(user=doctor_user, name="Dr. Test")
        self.patient.doctor = doctor_profile
        self.patient.save(update_fields=["doctor"])
        self.client.force_login(doctor_user)

        mock_ps.return_value.get_guard_days.return_value = (10, 20)
        mock_history.get_last_medical_history.return_value = None
        mock_cycle.return_value = None
        mock_lib.return_value = []

        today = date.today()
        mock_order = MagicMock()
        mock_order.start_date = today - timedelta(days=1)
        mock_order.end_date = today + timedelta(days=1)
        mock_get_orders.return_value = [mock_order]

        def _fake_metrics(*, patient_id, adherence_type, **kwargs):
            if adherence_type == choices.PlanItemCategory.MEDICATION:
                return {
                    "type": adherence_type,
                    "start_date": today - timedelta(days=7),
                    "end_date": today - timedelta(days=1),
                    "total": 10,
                    "completed": 5,
                    "rate": 0.5,
                }
            if adherence_type == MONITORING_ADHERENCE_ALL:
                return {
                    "type": adherence_type,
                    "start_date": today - timedelta(days=7),
                    "end_date": today - timedelta(days=1),
                    "total": 20,
                    "completed": 10,
                    "rate": 0.5,
                }
            raise AssertionError(f"Unexpected adherence_type: {adherence_type}")

        mock_get_adherence_metrics.side_effect = _fake_metrics

        url = reverse("web_doctor:patient_workspace_section", args=[self.patient.id, "home"])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertTrue(
            "用药依从率：50%（5/10）" in content,
            "依从性展示缺少用药依从率（未开始输出预期文本）。",
        )
        self.assertTrue(
            "常规监测综合依从率：50%（10/20）" in content,
            "依从性展示缺少常规监测综合依从率（未开始输出预期文本）。",
        )
