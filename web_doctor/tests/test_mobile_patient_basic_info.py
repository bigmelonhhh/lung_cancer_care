from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from health_data.models import MedicalHistory
from market.models import Order, Product
from users.models import DoctorProfile, PatientProfile

User = get_user_model()


class MobilePatientBasicInfoTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="doc_mobile_basic_info",
            password="password",
            user_type=2,
            phone="13900139011",
        )
        self.doctor_profile = DoctorProfile.objects.create(user=self.user, name="Dr. BasicInfo")
        self.user.doctor_profile = self.doctor_profile
        self.user.save()

        self.other_user = User.objects.create_user(
            username="doc_mobile_basic_info_other",
            password="password",
            user_type=2,
            phone="13900139012",
        )
        self.other_doctor_profile = DoctorProfile.objects.create(user=self.other_user, name="Dr. Other")
        self.other_user.doctor_profile = self.other_doctor_profile
        self.other_user.save()

        self.patient = PatientProfile.objects.create(
            name="张三",
            phone="13800138301",
            doctor=self.doctor_profile,
            id_card="310101199001011234",
            address="上海市浦东新区XX路",
            birth_date=timezone.localdate() - timedelta(days=30 * 365),
        )
        self.other_patient = PatientProfile.objects.create(
            name="李四",
            phone="13800138302",
            doctor=self.other_doctor_profile,
        )

        self.product = Product.objects.create(
            name="VIP 监护服务",
            price=Decimal("199.00"),
            duration_days=30,
            is_active=True,
        )

    def test_basic_info_page_renders(self):
        self.client.force_login(self.user)
        url = reverse("web_doctor:mobile_patient_basic_info") + f"?patient_id={self.patient.id}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "web_doctor/mobile/patient_basic_info.html")
        content = response.content.decode("utf-8")
        self.assertIn("患者基本信息", content)
        self.assertIn(self.patient.name, content)
        self.assertIn("/api/doctor/mobile/patient-profile/", content)
        self.assertIn("/api/doctor/mobile/medical-info/", content)
        self.assertIn("/api/doctor/mobile/member-info/", content)

    def test_basic_info_page_denies_unrelated_patient(self):
        self.client.force_login(self.user)
        url = reverse("web_doctor:mobile_patient_basic_info") + f"?patient_id={self.other_patient.id}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 400)

    def test_patient_profile_api_shape(self):
        self.client.force_login(self.user)
        url = reverse("web_doctor:mobile_api_patient_profile") + f"?patient_id={self.patient.id}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("success"))
        patient_info = payload.get("patient_info") or {}
        self.assertEqual(patient_info.get("name"), self.patient.name)
        self.assertIn("gender", patient_info)
        self.assertEqual(patient_info.get("phone"), self.patient.phone)
        self.assertIn("birth_date", patient_info)
        self.assertIn("address", patient_info)
        self.assertIn("emergency_contact", patient_info)
        self.assertIn("emergency_relation", patient_info)
        self.assertIn("emergency_phone", patient_info)
        self.assertIn("relations", patient_info)
        self.assertNotIn("id_card", patient_info)
        self.assertNotIn("age", patient_info)

    def test_medical_info_api_returns_latest(self):
        MedicalHistory.objects.create(
            patient=self.patient,
            tumor_diagnosis="I期肺腺癌",
            risk_factors="癌症家族史",
            clinical_diagnosis="右肺上叶病变",
            genetic_test="EGFR 19外显子缺失",
            past_medical_history="高血压5年",
            surgical_information="CT引导下肺穿刺活检术",
            created_by=self.user,
        )

        self.client.force_login(self.user)
        url = reverse("web_doctor:mobile_api_medical_info") + f"?patient_id={self.patient.id}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("success"))
        medical_info = payload.get("medical_info") or {}
        self.assertEqual(medical_info.get("diagnosis"), "I期肺腺癌")
        self.assertEqual(medical_info.get("history"), "高血压5年")
        self.assertNotIn("medical_display", payload)
        self.assertEqual(medical_info.get("risk_factors"), "癌症家族史")
        self.assertEqual(medical_info.get("clinical_diagnosis"), "右肺上叶病变")
        self.assertEqual(medical_info.get("gene_test"), "EGFR 19外显子缺失")
        self.assertEqual(medical_info.get("surgery"), "CT引导下肺穿刺活检术")

    def test_member_info_api_paid_and_dates(self):
        Order.objects.create(
            patient=self.patient,
            product=self.product,
            amount=Decimal("199.00"),
            status=Order.Status.PAID,
            paid_at=timezone.now() - timedelta(days=1),
        )

        self.client.force_login(self.user)
        url = reverse("web_doctor:mobile_api_member_info") + f"?patient_id={self.patient.id}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("success"))
        member_info = payload.get("member_info") or {}
        self.assertEqual(member_info.get("member_type"), "付费")
        self.assertTrue(member_info.get("package_start_date"))
        self.assertTrue(member_info.get("package_end_date"))

    def test_apis_denies_unrelated_patient(self):
        self.client.force_login(self.user)

        url = reverse("web_doctor:mobile_api_patient_profile") + f"?patient_id={self.other_patient.id}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

        url = reverse("web_doctor:mobile_api_medical_info") + f"?patient_id={self.other_patient.id}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

        url = reverse("web_doctor:mobile_api_member_info") + f"?patient_id={self.other_patient.id}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)
