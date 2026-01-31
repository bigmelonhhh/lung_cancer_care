from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from users.models import DoctorProfile, PatientProfile

User = get_user_model()


class MobileManageMetricsTests(TestCase):
    def setUp(self):
        self.doctor_user = User.objects.create_user(
            username="doc_manage_metrics",
            password="password",
            user_type=2,
            phone="13900139031",
        )
        self.doctor_profile = DoctorProfile.objects.create(user=self.doctor_user, name="Dr. Metrics")
        self.doctor_user.doctor_profile = self.doctor_profile
        self.doctor_user.save()

        self.patient = PatientProfile.objects.create(
            name="患者A",
            phone="13800138231",
            doctor=self.doctor_profile,
        )

        self.unauthorized_user = User.objects.create_user(
            username="sales_manage_metrics",
            password="password",
            user_type=3,
            phone="13900139032",
        )

    def test_manage_metrics_denies_non_doctor_user(self):
        self.client.force_login(self.unauthorized_user)
        url = reverse("web_doctor:mobile_health_records")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_manage_metrics_requires_valid_patient_id(self):
        self.client.force_login(self.doctor_user)
        url = reverse("web_doctor:mobile_health_records")

        response_missing = self.client.get(url)
        self.assertEqual(response_missing.status_code, 400)

        response_invalid = self.client.get(f"{url}?patient_id=abc")
        self.assertEqual(response_invalid.status_code, 400)

    def test_health_record_detail_returns_empty_list_when_no_data(self):
        self.client.force_login(self.doctor_user)
        url = reverse("web_doctor:mobile_health_record_detail")
        response = self.client.get(
            f"{url}?type=temperature&title=体温&patient_id={self.patient.id}&month=2026-01&page=1",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload.get("records"), [])
