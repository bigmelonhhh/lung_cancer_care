from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from users import choices
from users.models import CustomUser, DoctorProfile, PatientProfile


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
