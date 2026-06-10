from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from health_data.models import HealthMetric, MetricType
from users.models import CustomUser, PatientProfile


class HealthCalendarSelectedDateRecordingTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = CustomUser.objects.create_user(
            username="testpatient_calendar_selected_date",
            password="password",
            wx_openid="test_openid_calendar_selected_date",
        )
        self.patient = PatientProfile.objects.create(user=self.user, name="Test Patient")
        self.client.force_login(self.user)

    def test_record_pages_render_selected_date_in_datetime_local_value(self):
        selected_date = "2026-01-11"
        cases = [
            reverse("web_patient:record_temperature"),
            reverse("web_patient:record_bp"),
            reverse("web_patient:record_spo2"),
            reverse("web_patient:record_weight"),
        ]
        for url in cases:
            resp = self.client.get(url, {"selected_date": selected_date})
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, f'value=\"{selected_date}T')

    def test_record_temperature_post_overrides_date_to_selected_date(self):
        selected_date = "2026-01-11"
        url = reverse("web_patient:record_temperature")
        resp = self.client.post(
            url,
            {
                "temperature": "36.5",
                "record_time": "2026-01-24 19:46",
                "record_time_touched": "1",
                "selected_date": selected_date,
            },
        )
        self.assertEqual(resp.status_code, 302)
        metric = HealthMetric.objects.filter(
            patient=self.patient, metric_type=MetricType.BODY_TEMPERATURE
        ).last()
        self.assertIsNotNone(metric)
        self.assertEqual(timezone.localtime(metric.measured_at).date().isoformat(), selected_date)

    def test_record_bp_post_overrides_date_to_selected_date(self):
        selected_date = "2026-01-11"
        url = reverse("web_patient:record_bp")
        resp = self.client.post(
            url,
            {
                "ssy": "120",
                "szy": "80",
                "heart": "75",
                "record_time": "2026-01-24 19:46",
                "record_time_touched": "1",
                "selected_date": selected_date,
            },
        )
        self.assertEqual(resp.status_code, 302)
        bp_metric = HealthMetric.objects.filter(
            patient=self.patient, metric_type=MetricType.BLOOD_PRESSURE
        ).last()
        hr_metric = HealthMetric.objects.filter(
            patient=self.patient, metric_type=MetricType.HEART_RATE
        ).last()
        self.assertIsNotNone(bp_metric)
        self.assertIsNotNone(hr_metric)
        self.assertEqual(timezone.localtime(bp_metric.measured_at).date().isoformat(), selected_date)
        self.assertEqual(timezone.localtime(hr_metric.measured_at).date().isoformat(), selected_date)
        self.assertEqual(
            timezone.localtime(bp_metric.measured_at).strftime("%Y-%m-%d %H:%M"),
            "2026-01-11 19:46",
        )

    @patch("web_patient.views.record.timezone.now")
    def test_record_bp_selected_date_uses_submit_current_time_when_not_touched(
        self, mock_now
    ):
        selected_date = "2026-01-11"
        mock_now.return_value = timezone.make_aware(datetime(2026, 1, 24, 10, 5, 30))
        resp = self.client.post(
            reverse("web_patient:record_bp"),
            {
                "ssy": "120",
                "szy": "80",
                "heart": "75",
                "record_time": "2026-01-24 10:01",
                "record_time_touched": "0",
                "selected_date": selected_date,
            },
        )

        self.assertEqual(resp.status_code, 302)
        bp_metric = HealthMetric.objects.filter(
            patient=self.patient,
            metric_type=MetricType.BLOOD_PRESSURE,
        ).last()
        hr_metric = HealthMetric.objects.filter(
            patient=self.patient,
            metric_type=MetricType.HEART_RATE,
        ).last()
        self.assertEqual(
            timezone.localtime(bp_metric.measured_at).strftime("%Y-%m-%d %H:%M:%S"),
            "2026-01-11 10:05:30",
        )
        self.assertEqual(bp_metric.measured_at, hr_metric.measured_at)

    def test_record_spo2_post_overrides_date_to_selected_date(self):
        selected_date = "2026-01-11"
        url = reverse("web_patient:record_spo2")
        resp = self.client.post(
            url,
            {
                "spo2": "98",
                "record_time": "2026-01-24 19:46",
                "record_time_touched": "1",
                "selected_date": selected_date,
            },
        )
        self.assertEqual(resp.status_code, 302)
        metric = HealthMetric.objects.filter(
            patient=self.patient, metric_type=MetricType.BLOOD_OXYGEN
        ).last()
        self.assertIsNotNone(metric)
        self.assertEqual(timezone.localtime(metric.measured_at).date().isoformat(), selected_date)

    def test_record_weight_post_overrides_date_to_selected_date(self):
        selected_date = "2026-01-11"
        url = reverse("web_patient:record_weight")
        resp = self.client.post(
            url,
            {
                "weight": "60.0",
                "record_time": "2026-01-24 19:46",
                "record_time_touched": "1",
                "selected_date": selected_date,
            },
        )
        self.assertEqual(resp.status_code, 302)
        metric = HealthMetric.objects.filter(
            patient=self.patient, metric_type=MetricType.WEIGHT
        ).last()
        self.assertIsNotNone(metric)
        self.assertEqual(timezone.localtime(metric.measured_at).date().isoformat(), selected_date)

