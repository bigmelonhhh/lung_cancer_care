import re
import json
from datetime import date, timedelta
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from core.models import Medication, PlanItem, TreatmentCycle, choices
from users.choices import UserType
from users.models import CustomUser, DoctorProfile, PatientProfile
from web_doctor.views import workspace


class TreatmentCycleQuickCreateViewTests(TestCase):
    def setUp(self):
        self.doctor_user = CustomUser.objects.create_user(
            username="doctor_cycle_quick_create",
            password="password123",
            user_type=UserType.DOCTOR,
            phone="13900009990",
        )
        self.doctor_profile = DoctorProfile.objects.create(user=self.doctor_user, name="张医生")

        patient_user = CustomUser.objects.create_user(
            username="patient_cycle_quick_create",
            password="password123",
            user_type=UserType.PATIENT,
            phone="13800009990",
            wx_openid="openid_cycle_quick_create",
        )
        self.patient = PatientProfile.objects.create(
            user=patient_user,
            doctor=self.doctor_profile,
            name="患者快捷新增",
            phone="13800009990",
            is_active=True,
        )
        other_patient_user = CustomUser.objects.create_user(
            username="patient_cycle_quick_other",
            password="password123",
            user_type=UserType.PATIENT,
            phone="13800009991",
            wx_openid="openid_cycle_quick_other",
        )
        self.other_patient = PatientProfile.objects.create(
            user=other_patient_user,
            doctor=self.doctor_profile,
            name="其他患者",
            phone="13800009991",
            is_active=True,
        )

        self.client.login(username="doctor_cycle_quick_create", password="password123")
        self.settings_url = reverse("web_doctor:patient_workspace_section", args=[self.patient.id, "settings"])
        self.quick_create_url = reverse(
            "web_doctor:patient_treatment_cycle_quick_create",
            args=[self.patient.id],
        )

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

    def test_settings_page_renders_quick_create_button_and_candidates_in_sorted_order(self):
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
        in_progress = TreatmentCycle.objects.create(
            patient=self.patient,
            name="进行中疗程",
            start_date=today - timedelta(days=2),
            end_date=today + timedelta(days=5),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        completed = TreatmentCycle.objects.create(
            patient=self.patient,
            name="已结束疗程",
            start_date=today - timedelta(days=30),
            end_date=today - timedelta(days=10),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )

        response = self.client.get(self.settings_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "快捷新增")
        self.assertContains(response, 'id="quick-cycle-modal"')
        html = response.content.decode("utf-8")
        candidate_ids = re.findall(r'data-quick-cycle-option\s+data-cycle-id="(\d+)"', html)
        self.assertEqual(candidate_ids, [str(in_progress.id), str(future.id), str(completed.id)])

    def test_quick_create_success_selects_new_cycle_and_triggers_success_message(self):
        self._patch_settings_dependencies()
        source_cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="参考疗程",
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 21),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.COMPLETED,
        )
        medication = Medication.objects.create(
            name="快捷复制药物",
            name_abbr="KJFZYW",
            default_dosage="10mg",
            default_frequency="qd",
            is_active=True,
        )
        PlanItem.objects.create(
            cycle=source_cycle,
            category=choices.PlanItemCategory.MEDICATION,
            template_id=medication.id,
            item_name=medication.name,
            schedule_days=[1, 8, 15],
            status=choices.PlanItemStatus.ACTIVE,
            created_by=self.doctor_user,
            updated_by=self.doctor_user,
        )

        response = self.client.post(
            self.quick_create_url,
            {
                "source_cycle_id": str(source_cycle.id),
                "name": "新快捷疗程",
                "start_date": "2025-02-01",
                "cycle_days_mode": "21",
            },
        )

        self.assertEqual(response.status_code, 200)
        new_cycle = TreatmentCycle.objects.get(name="新快捷疗程")
        self.assertEqual(PlanItem.objects.filter(cycle=new_cycle).count(), 1)
        trigger_payload = json.loads(response["HX-Trigger"])
        self.assertIn("plan-success", trigger_payload)
        self.assertIn("已复制 1 条计划", trigger_payload["plan-success"]["message"])
        self.assertContains(response, "当前选中：")
        self.assertContains(response, "新快捷疗程")
        plan_table_url = reverse("web_doctor:patient_settings_plan_table", args=[self.patient.id])
        self.assertContains(response, f'hx-get="{plan_table_url}?cycle_id={new_cycle.id}"')

    def test_quick_create_validation_error_reopens_modal_and_preserves_inputs(self):
        self._patch_settings_dependencies()
        source_cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="回填参考疗程",
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 21),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.COMPLETED,
        )

        response = self.client.post(
            self.quick_create_url,
            {
                "source_cycle_id": str(source_cycle.id),
                "name": "错误快捷疗程",
                "start_date": "",
                "cycle_days_mode": "21",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(TreatmentCycle.objects.filter(name="错误快捷疗程").exists())
        self.assertContains(response, "请填写开始日期。")
        html = response.content.decode("utf-8")
        self.assertIn('data-auto-open="1"', html)
        self.assertIn(f'value="{source_cycle.id}"', html)
        self.assertIn('value="错误快捷疗程"', html)

    def test_quick_create_with_empty_source_plan_returns_zero_copy_success_message(self):
        self._patch_settings_dependencies()
        source_cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="空计划疗程",
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 21),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.COMPLETED,
        )

        response = self.client.post(
            self.quick_create_url,
            {
                "source_cycle_id": str(source_cycle.id),
                "name": "空计划新疗程",
                "start_date": "2025-02-01",
                "cycle_days_mode": "21",
            },
        )

        self.assertEqual(response.status_code, 200)
        new_cycle = TreatmentCycle.objects.get(name="空计划新疗程")
        self.assertFalse(PlanItem.objects.filter(cycle=new_cycle).exists())
        trigger_payload = json.loads(response["HX-Trigger"])
        self.assertIn("plan-success", trigger_payload)
        self.assertIn("参考疗程下无可复制计划", trigger_payload["plan-success"]["message"])

    def test_quick_create_rejects_source_cycle_from_other_patient(self):
        self._patch_settings_dependencies()
        other_cycle = TreatmentCycle.objects.create(
            patient=self.other_patient,
            name="其他患者参考疗程",
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 21),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.COMPLETED,
        )

        response = self.client.post(
            self.quick_create_url,
            {
                "source_cycle_id": str(other_cycle.id),
                "name": "跨患者快捷疗程",
                "start_date": "2025-02-01",
                "cycle_days_mode": "21",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(TreatmentCycle.objects.filter(name="跨患者快捷疗程").exists())
        self.assertContains(response, "参考疗程与当前患者不匹配。")
        self.assertContains(response, 'data-auto-open="1"')
