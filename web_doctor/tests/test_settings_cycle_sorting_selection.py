from datetime import date, timedelta
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from core.models import TreatmentCycle, choices
from users.choices import UserType
from users.models import CustomUser, DoctorProfile, PatientProfile
from web_doctor.views import workspace


class SettingsCycleSortingSelectionTests(TestCase):
    def setUp(self):
        self.doctor_user = CustomUser.objects.create_user(
            username="doctor_cycle_sort",
            password="password123",
            user_type=UserType.DOCTOR,
            phone="13900007770",
        )
        self.doctor_profile = DoctorProfile.objects.create(user=self.doctor_user, name="张医生")

        patient_user = CustomUser.objects.create_user(
            username="patient_cycle_sort",
            password="password123",
            user_type=UserType.PATIENT,
            phone="13800007770",
            wx_openid="openid_cycle_sort",
        )
        self.patient = PatientProfile.objects.create(
            user=patient_user,
            doctor=self.doctor_profile,
            name="患者B",
            phone="13800007770",
            is_active=True,
        )
        self.client.login(username="doctor_cycle_sort", password="password123")

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

    def test_sort_cycles_prioritizes_in_progress_then_not_started_then_completed_then_terminated(self):
        today = date.today()
        cycles = [
            TreatmentCycle(
                patient=self.patient,
                name="未来疗程",
                start_date=today + timedelta(days=10),
                end_date=today + timedelta(days=30),
                cycle_days=21,
                status=choices.TreatmentCycleStatus.IN_PROGRESS,
            ),
            TreatmentCycle(
                patient=self.patient,
                name="已终止疗程",
                start_date=today - timedelta(days=5),
                end_date=today + timedelta(days=10),
                cycle_days=21,
                status=choices.TreatmentCycleStatus.TERMINATED,
            ),
            TreatmentCycle(
                patient=self.patient,
                name="进行中疗程",
                start_date=today - timedelta(days=2),
                end_date=today + timedelta(days=5),
                cycle_days=21,
                status=choices.TreatmentCycleStatus.IN_PROGRESS,
            ),
            TreatmentCycle(
                patient=self.patient,
                name="已结束疗程",
                start_date=today - timedelta(days=30),
                end_date=today - timedelta(days=10),
                cycle_days=21,
                status=choices.TreatmentCycleStatus.IN_PROGRESS,
            ),
        ]

        sorted_cycles = workspace._sort_cycles_for_settings(cycles, today=today)
        self.assertEqual(
            [c.name for c in sorted_cycles],
            ["进行中疗程", "未来疗程", "已结束疗程", "已终止疗程"],
        )

    def test_default_selected_cycle_is_first_in_sorted_list_when_in_progress_exists(self):
        self._patch_settings_dependencies()
        today = date.today()

        TreatmentCycle.objects.create(
            patient=self.patient,
            name="未来疗程",
            start_date=today + timedelta(days=10),
            end_date=today + timedelta(days=30),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        in_progress = TreatmentCycle.objects.create(
            patient=self.patient,
            name="进行中疗程",
            start_date=today - timedelta(days=2),
            end_date=today + timedelta(days=5),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        TreatmentCycle.objects.create(
            patient=self.patient,
            name="已结束疗程",
            start_date=today - timedelta(days=30),
            end_date=today - timedelta(days=10),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )

        context = workspace._build_settings_context(self.patient)
        self.assertIsNotNone(context.get("selected_cycle"))
        self.assertEqual(context["selected_cycle"].id, in_progress.id)
        self.assertEqual(context["cycle_page"].object_list[0].id, in_progress.id)

    def test_no_in_progress_keeps_original_order_and_selects_first(self):
        self._patch_settings_dependencies()
        today = date.today()

        future = TreatmentCycle.objects.create(
            patient=self.patient,
            name="未来疗程",
            start_date=today + timedelta(days=10),
            end_date=today + timedelta(days=30),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        TreatmentCycle.objects.create(
            patient=self.patient,
            name="已终止疗程",
            start_date=today - timedelta(days=5),
            end_date=today + timedelta(days=10),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.TERMINATED,
        )
        TreatmentCycle.objects.create(
            patient=self.patient,
            name="已结束疗程",
            start_date=today - timedelta(days=30),
            end_date=today - timedelta(days=10),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )

        context = workspace._build_settings_context(self.patient)
        self.assertIsNotNone(context.get("selected_cycle"))
        self.assertEqual(context["selected_cycle"].id, future.id)

        page_names = [c.name for c in context["cycle_page"].object_list]
        self.assertEqual(page_names[0], "未来疗程")

    def test_settings_page_renders_selected_in_progress_first(self):
        self._patch_settings_dependencies()
        today = date.today()

        TreatmentCycle.objects.create(
            patient=self.patient,
            name="未来疗程",
            start_date=today + timedelta(days=10),
            end_date=today + timedelta(days=30),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        TreatmentCycle.objects.create(
            patient=self.patient,
            name="进行中疗程",
            start_date=today - timedelta(days=2),
            end_date=today + timedelta(days=5),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )

        url = reverse("web_doctor:patient_workspace_section", args=[self.patient.id, "settings"])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "当前选中：")
        self.assertContains(response, "进行中疗程")

        html = response.content.decode("utf-8")
        self.assertLess(html.find("进行中疗程"), html.find("未来疗程"))
