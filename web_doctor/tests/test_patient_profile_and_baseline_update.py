from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from users import choices
from users.models import CustomUser, DoctorProfile, PatientProfile
from web_doctor.forms import PatientHealthBaselineForm


class DoctorPatientProfileAndBaselineUpdateTests(TestCase):
    def setUp(self):
        self.doctor_user = CustomUser.objects.create_user(
            username="doctor_profile_editor",
            password="password",
            user_type=choices.UserType.DOCTOR,
            phone="13900139101",
        )
        self.doctor = DoctorProfile.objects.create(
            user=self.doctor_user,
            name="Dr. Profile",
        )
        self.patient = PatientProfile.objects.create(
            name="张三",
            phone="13800139101",
            doctor=self.doctor,
            birth_date="1980-01-02",
            address="上海市浦东新区",
            ec_name="李四",
            ec_relation="配偶",
            ec_phone="13800139102",
        )

    def test_profile_update_saves_and_renders_demographic_fields(self):
        self.client.force_login(self.doctor_user)
        response = self.client.post(
            reverse("web_doctor:patient_profile_update", args=[self.patient.id]),
            {
                "name": "张三",
                "phone": self.patient.phone,
                "gender": "男",
                "birth_date": "1980-01-02",
                "marital_status": "已婚",
                "ethnicity": "汉族",
                "native_place": "江苏南京",
                "occupation": "工程师",
                "address": "上海市浦东新区",
                "emergency_contact": "李四",
                "emergency_relation": "配偶",
                "emergency_phone": "13800139102",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.marital_status, "已婚")
        self.assertEqual(self.patient.ethnicity, "汉族")
        self.assertEqual(self.patient.native_place, "江苏南京")
        self.assertEqual(self.patient.occupation, "工程师")

        content = response.content.decode("utf-8")
        self.assertIn("人口学信息", content)
        self.assertIn("已婚", content)
        self.assertIn("江苏南京", content)
        self.assertIn("工程师", content)

    def test_health_metrics_update_saves_and_renders_height_baseline(self):
        self.patient.marital_status = "已婚"
        self.patient.occupation = "工程师"
        self.patient.save(update_fields=["marital_status", "occupation"])

        self.client.force_login(self.doctor_user)
        response = self.client.post(
            reverse("web_doctor:patient_health_metrics_update", args=[self.patient.id]),
            {
                "blood_oxygen": "98",
                "sbp": "120",
                "dbp": "80",
                "heart_rate": "72",
                "weight": "68.5",
                "height": "170.5",
                "temperature": "36.6",
                "steps": "6000",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.baseline_height, Decimal("170.5"))
        self.assertEqual(self.patient.marital_status, "已婚")
        self.assertEqual(self.patient.occupation, "工程师")

        content = response.content.decode("utf-8")
        self.assertIn("身高", content)
        self.assertIn("170.5 cm", content)

    def test_health_metrics_update_saves_and_renders_new_baselines(self):
        self.client.force_login(self.doctor_user)
        response = self.client.post(
            reverse("web_doctor:patient_health_metrics_update", args=[self.patient.id]),
            {
                "blood_glucose": "6.2",
                "blood_ketone": "0.6",
                "uric_acid": "420",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.baseline_blood_glucose, Decimal("6.2"))
        self.assertEqual(self.patient.baseline_blood_ketone, Decimal("0.6"))
        self.assertEqual(self.patient.baseline_uric_acid, 420)
        content = response.content.decode("utf-8")
        self.assertIn("6.2 mmol/L", content)
        self.assertIn("0.6 mmol/L", content)
        self.assertIn("420 μmol/L", content)

    def test_health_baseline_form_accepts_zero_and_rejects_negative_values(self):
        zero_form = PatientHealthBaselineForm(
            {
                "blood_glucose": "0",
                "blood_ketone": "0",
                "uric_acid": "0",
            }
        )
        self.assertTrue(zero_form.is_valid(), zero_form.errors)
        self.assertEqual(zero_form.cleaned_data["baseline_blood_glucose"], Decimal("0"))

        negative_form = PatientHealthBaselineForm({"blood_glucose": "-0.1"})
        self.assertFalse(negative_form.is_valid())
        self.assertIn("blood_glucose", negative_form.errors)
