from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from health_data.models import HealthMetric, MetricType
from users.models import CustomUser, PatientProfile


class HealthRecordDetailRefreshFlagTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = CustomUser.objects.create_user(
            username="testpatient_health_record_detail_refresh_flag",
            password="password",
            wx_openid="test_openid_health_record_detail_refresh_flag",
        )
        self.patient = PatientProfile.objects.create(user=self.user, name="Test Patient")
        self.client.force_login(self.user)

    def test_detail_template_contains_refresh_flag_pageshow_logic(self):
        url = reverse("web_patient:health_record_detail")
        month = timezone.localtime(timezone.now()).strftime("%Y-%m")
        resp = self.client.get(
            url,
            {
                "type": "temperature",
                "title": "体温",
                "month": month,
                "source": "health_records",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "refresh_flag")
        self.assertContains(resp, "pageshow")
        self.assertContains(resp, "refreshRecordList")

    def test_detail_ajax_returns_newest_metric_after_creation(self):
        url = reverse("web_patient:health_record_detail")
        month = timezone.localtime(timezone.now()).strftime("%Y-%m")
        HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BODY_TEMPERATURE,
            source="manual",
            measured_at=timezone.now(),
            value_main=Decimal("36.5"),
        )
        resp = self.client.get(
            url,
            {"type": "temperature", "title": "体温", "month": month},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertTrue(payload["records"])
        self.assertEqual(payload["records"][0]["data"][0]["key"], "temperature")

