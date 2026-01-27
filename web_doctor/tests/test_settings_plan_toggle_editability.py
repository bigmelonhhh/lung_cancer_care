import re
from datetime import date, timedelta
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from core.models import PlanItem, TreatmentCycle, choices
from users.choices import UserType
from users.models import CustomUser, DoctorProfile, PatientProfile


class SettingsPlanToggleEditabilityTests(TestCase):
    def setUp(self):
        self.doctor_user = CustomUser.objects.create_user(
            username="doctor_plan_toggle",
            password="password123",
            user_type=UserType.DOCTOR,
            phone="13900006660",
        )
        self.doctor_profile = DoctorProfile.objects.create(user=self.doctor_user, name="张医生")

        patient_user = CustomUser.objects.create_user(
            username="patient_plan_toggle",
            password="password123",
            user_type=UserType.PATIENT,
            phone="13800006660",
            wx_openid="openid_plan_toggle",
        )
        self.patient = PatientProfile.objects.create(
            user=patient_user,
            doctor=self.doctor_profile,
            name="患者C",
            phone="13800006660",
            is_active=True,
        )
        self.client.login(username="doctor_plan_toggle", password="password123")

    def _patch_settings_dependencies(self, cycle_plan_view):
        patches = [
            patch("web_doctor.views.workspace.get_active_medication_library", return_value=[]),
            patch("web_doctor.views.workspace.PlanItemService.get_cycle_plan_view", return_value=cycle_plan_view),
            patch("web_doctor.views.workspace.MedicalHistoryService.get_last_medical_history", return_value=None),
            patch("web_doctor.views.workspace.get_active_treatment_cycle", return_value=None),
            patch("web_doctor.views.workspace.PatientService"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        from web_doctor.views import workspace

        patient_service_mock = workspace.PatientService.return_value
        patient_service_mock.get_patient_family_members.return_value = []

    def _build_cycle_plan_view(self, cycle, plan_items):
        return {
            "medications": [
                {
                    "library_id": 101,
                    "name": "测试用药",
                    "type": "口服",
                    "current_dosage": "10mg",
                    "current_usage": "每日1次",
                    "method_display": "",
                    "is_active": True,
                    "schedule_days": [1, 2],
                    "plan_item_id": plan_items["med"].id,
                }
            ],
            "checkups": [
                {
                    "library_id": 201,
                    "name": "测试复查",
                    "related_report_type": "",
                    "is_active": True,
                    "schedule_days": [1],
                    "plan_item_id": plan_items["chk"].id,
                }
            ],
            "questionnaires": [
                {
                    "library_id": 301,
                    "name": "测试问卷",
                    "is_active": True,
                    "schedule_days": [1],
                    "plan_item_id": plan_items["q"].id,
                }
            ],
            "monitorings": [
                {
                    "library_id": 401,
                    "name": "测试监测",
                    "is_active": True,
                    "schedule_days": [1],
                    "plan_item_id": plan_items["m"].id,
                }
            ],
        }

    def _create_plan_items(self, cycle):
        plan_items = {}
        plan_items["med"] = PlanItem.objects.create(
            cycle=cycle,
            category=choices.PlanItemCategory.MEDICATION,
            template_id=101,
            item_name="测试用药",
            schedule_days=[1, 2],
            status=choices.PlanItemStatus.ACTIVE,
        )
        plan_items["chk"] = PlanItem.objects.create(
            cycle=cycle,
            category=choices.PlanItemCategory.CHECKUP,
            template_id=201,
            item_name="测试复查",
            schedule_days=[1],
            status=choices.PlanItemStatus.ACTIVE,
        )
        plan_items["q"] = PlanItem.objects.create(
            cycle=cycle,
            category=choices.PlanItemCategory.QUESTIONNAIRE,
            template_id=301,
            item_name="测试问卷",
            schedule_days=[1],
            status=choices.PlanItemStatus.ACTIVE,
        )
        plan_items["m"] = PlanItem.objects.create(
            cycle=cycle,
            category=choices.PlanItemCategory.MONITORING,
            template_id=401,
            item_name="测试监测",
            schedule_days=[1],
            status=choices.PlanItemStatus.ACTIVE,
        )
        return plan_items

    def _assert_toggle_enabled_for_types(self, html):
        self.assertIsNone(re.search(r"data-monitoring-toggle[^>]*disabled", html))
        self.assertIsNone(re.search(r"data-checkup-toggle[^>]*disabled", html))
        self.assertIsNone(re.search(r"data-questionnaire-toggle[^>]*disabled", html))
        self.assertNotIn('data-readonly-row="1"', html)

    def _assert_toggle_disabled_for_types(self, html):
        self.assertIsNotNone(re.search(r"data-monitoring-toggle[^>]*disabled", html))
        self.assertIsNotNone(re.search(r"data-checkup-toggle[^>]*disabled", html))
        self.assertIsNotNone(re.search(r"data-questionnaire-toggle[^>]*disabled", html))
        self.assertIn('data-readonly-row="1"', html)

    def test_not_started_cycle_allows_plan_toggles(self):
        today = date.today()
        cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="未开始疗程",
            start_date=today + timedelta(days=3),
            end_date=today + timedelta(days=23),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        plan_items = self._create_plan_items(cycle)
        cycle_plan_view = self._build_cycle_plan_view(cycle, plan_items)
        self._patch_settings_dependencies(cycle_plan_view)

        url = reverse(
            "web_doctor:patient_workspace_section",
            args=[self.patient.id, "settings"],
        ) + f"?cycle_id={cycle.id}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self._assert_toggle_enabled_for_types(html)

    def test_in_progress_cycle_allows_plan_toggles(self):
        today = date.today()
        cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="进行中疗程",
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=20),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        plan_items = self._create_plan_items(cycle)
        cycle_plan_view = self._build_cycle_plan_view(cycle, plan_items)
        self._patch_settings_dependencies(cycle_plan_view)

        url = reverse(
            "web_doctor:patient_workspace_section",
            args=[self.patient.id, "settings"],
        ) + f"?cycle_id={cycle.id}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self._assert_toggle_enabled_for_types(html)

    def test_completed_cycle_disables_plan_toggles(self):
        today = date.today()
        cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="已结束疗程",
            start_date=today - timedelta(days=30),
            end_date=today - timedelta(days=10),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        plan_items = self._create_plan_items(cycle)
        cycle_plan_view = self._build_cycle_plan_view(cycle, plan_items)
        self._patch_settings_dependencies(cycle_plan_view)

        url = reverse(
            "web_doctor:patient_workspace_section",
            args=[self.patient.id, "settings"],
        ) + f"?cycle_id={cycle.id}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self._assert_toggle_disabled_for_types(html)

    def test_terminated_cycle_disables_plan_toggles(self):
        today = date.today()
        cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="已终止疗程",
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=20),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.TERMINATED,
        )
        plan_items = self._create_plan_items(cycle)
        cycle_plan_view = self._build_cycle_plan_view(cycle, plan_items)
        self._patch_settings_dependencies(cycle_plan_view)

        url = reverse(
            "web_doctor:patient_workspace_section",
            args=[self.patient.id, "settings"],
        ) + f"?cycle_id={cycle.id}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self._assert_toggle_disabled_for_types(html)
