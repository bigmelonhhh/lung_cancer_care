import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from health_data.models import HealthMetric, MetricType
from users.models import DoctorProfile, PatientProfile

User = get_user_model()


class MobileHealthRecordDetailPaginationTests(TestCase):
    def setUp(self):
        self.doctor_user = User.objects.create_user(
            username="doctor_mobile_record_pagination",
            password="password",
            user_type=2,
            phone="13900139071",
        )
        self.doctor_profile = DoctorProfile.objects.create(
            user=self.doctor_user,
            name="Dr. Record Pagination",
        )
        self.doctor_user.doctor_profile = self.doctor_profile
        self.doctor_user.save()

        self.patient = PatientProfile.objects.create(
            name="患者分页A",
            phone="13800138071",
            doctor=self.doctor_profile,
        )
        self.client.force_login(self.doctor_user)
        self.url = reverse("web_doctor:mobile_health_record_detail")
        self.tz = timezone.get_current_timezone()

    def _create_temperature(self, year, month, day):
        HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BODY_TEMPERATURE,
            measured_at=timezone.make_aware(
                datetime.datetime(year, month, day, 8, 0),
                self.tz,
            ),
            value_main=Decimal("36.5"),
        )

    def _create_bp(self, year, month, day, ssy="120", szy="80"):
        HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BLOOD_PRESSURE,
            measured_at=timezone.make_aware(
                datetime.datetime(year, month, day, 8, 0),
                self.tz,
            ),
            value_main=Decimal(ssy),
            value_sub=Decimal(szy),
        )

    def test_initial_batch_uses_fixed_size_for_doctor_mobile(self):
        for day in range(28, 20, -1):
            self._create_temperature(2025, 3, day)

        response = self.client.get(
            self.url,
            {
                "type": "temperature",
                "title": "体温",
                "patient_id": self.patient.id,
                "month": "2025-03",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["records"]), 6)
        self.assertEqual(response.context["next_cursor_month"], "2025-03")
        self.assertEqual(response.context["next_cursor_offset"], 6)

    def test_initial_batch_can_fill_previous_month_for_doctor_mobile(self):
        for day in (28, 18):
            self._create_temperature(2025, 3, day)
        for day in (26, 22, 18, 12, 8):
            self._create_temperature(2025, 2, day)

        response = self.client.get(
            self.url,
            {
                "type": "temperature",
                "title": "体温",
                "patient_id": self.patient.id,
                "month": "2025-03",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["records"]), 6)
        self.assertEqual(response.context["next_cursor_month"], "2025-02")
        self.assertEqual(response.context["next_cursor_offset"], 4)

        ajax_response = self.client.get(
            self.url,
            {
                "type": "temperature",
                "title": "体温",
                "patient_id": self.patient.id,
                "month": "2025-03",
                "cursor_month": "2025-02",
                "cursor_offset": 4,
                "limit": 6,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(ajax_response.status_code, 200)
        payload = ajax_response.json()
        self.assertEqual([item["date"] for item in payload["records"]], ["2025-02-08"])
        self.assertFalse(payload["has_more"])
        self.assertIsNone(payload["next_cursor_month"])
        self.assertIsNone(payload["next_cursor_offset"])

    def test_bp_record_renders_single_line_value_for_doctor_mobile(self):
        self._create_bp(2025, 3, 28, "126", "82")

        response = self.client.get(
            self.url,
            {
                "type": "bp",
                "title": "血压",
                "patient_id": self.patient.id,
                "month": "2025-03",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "血压:")
        self.assertContains(response, "126 / 82")
