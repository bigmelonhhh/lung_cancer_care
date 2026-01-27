from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse

from core.models import TreatmentCycle, choices
from users.choices import UserType
from users.models import CustomUser, DoctorProfile, PatientProfile


class SettingsCycleStatusDisplayTests(TestCase):
    def setUp(self):
        self.doctor_user = CustomUser.objects.create_user(
            username="doctor_cycle_status",
            password="password123",
            user_type=UserType.DOCTOR,
            phone="13900008880",
        )
        self.doctor_profile = DoctorProfile.objects.create(user=self.doctor_user, name="张医生")

        patient_user = CustomUser.objects.create_user(
            username="patient_cycle_status",
            password="password123",
            user_type=UserType.PATIENT,
            phone="13800008880",
            wx_openid="openid_cycle_status",
        )
        self.patient = PatientProfile.objects.create(
            user=patient_user,
            doctor=self.doctor_profile,
            name="患者A",
            phone="13800008880",
            is_active=True,
        )
        self.client.login(username="doctor_cycle_status", password="password123")

    def test_settings_page_renders_runtime_cycle_status_labels(self):
        today = date.today()
        TreatmentCycle.objects.create(
            patient=self.patient,
            name="未来疗程",
            start_date=today + timedelta(days=5),
            end_date=today + timedelta(days=15),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        TreatmentCycle.objects.create(
            patient=self.patient,
            name="进行中疗程",
            start_date=today - timedelta(days=2),
            end_date=today + timedelta(days=2),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        TreatmentCycle.objects.create(
            patient=self.patient,
            name="已结束疗程",
            start_date=today - timedelta(days=20),
            end_date=today - timedelta(days=1),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )

        url = reverse("web_doctor:patient_workspace_section", args=[self.patient.id, "settings"])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "状态：未开始")
        self.assertContains(response, "状态：进行中")
        self.assertContains(response, "状态：已结束")
