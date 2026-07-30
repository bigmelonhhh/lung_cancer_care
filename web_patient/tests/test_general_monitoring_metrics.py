from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from health_data.models import (
    HealthMetric,
    MetricMeasurementContext,
    MetricSource,
    MetricType,
)
from users.models import CustomUser, PatientProfile
from web_patient.views.home import _build_daily_plans


class GeneralMonitoringMetricViewTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username="general_monitoring_patient",
            password="password",
            wx_openid="general_monitoring_openid",
        )
        self.patient = PatientProfile.objects.create(
            user=self.user,
            name="监测患者",
        )
        self.client.force_login(self.user)

    def test_invalid_monitoring_slug_returns_404(self):
        response = self.client.get(
            reverse("web_patient:record_general_monitoring", args=["unknown"])
        )

        self.assertEqual(response.status_code, 404)

    def test_glucose_requires_measurement_context(self):
        response = self.client.post(
            reverse("web_patient:record_general_monitoring", args=["glucose"]),
            {
                "value": "6.2",
                "record_time": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
                "record_time_touched": "1",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            HealthMetric.objects.filter(
                patient=self.patient,
                metric_type=MetricType.BLOOD_GLUCOSE,
            ).exists()
        )

    def test_general_monitoring_value_must_be_non_negative(self):
        response = self.client.post(
            reverse("web_patient:record_general_monitoring", args=["uric_acid"]),
            {"value": "-1"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            HealthMetric.objects.filter(
                patient=self.patient,
                metric_type=MetricType.URIC_ACID,
            ).exists()
        )

    def test_glucose_submission_persists_context_and_returns_success(self):
        response = self.client.post(
            reverse("web_patient:record_general_monitoring", args=["glucose"]),
            {
                "value": "6.2",
                "measurement_context": MetricMeasurementContext.FASTING,
                "record_time": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
                "record_time_touched": "1",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "success")
        metric = HealthMetric.objects.get(
            patient=self.patient,
            metric_type=MetricType.BLOOD_GLUCOSE,
        )
        self.assertEqual(metric.value_main, Decimal("6.20"))
        self.assertEqual(metric.measurement_context, MetricMeasurementContext.FASTING)
        self.assertEqual(metric.source, MetricSource.MANUAL)

    def test_ketone_submission_does_not_store_measurement_context(self):
        response = self.client.post(
            reverse("web_patient:record_general_monitoring", args=["ketone"]),
            {
                "value": "0.5",
                "measurement_context": MetricMeasurementContext.RANDOM,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        metric = HealthMetric.objects.get(
            patient=self.patient,
            metric_type=MetricType.BLOOD_KETONE,
        )
        self.assertIsNone(metric.measurement_context)

    def test_calendar_source_returns_selected_date_without_home_optimistic_marker(
        self,
    ):
        template_source = (
            Path(settings.BASE_DIR)
            / "templates/web_patient/record_general_monitoring.html"
        ).read_text(encoding="utf-8")

        source_branch = template_source[
            template_source.index(
                "const source = new URLSearchParams(window.location.search).get('source');"
            ) :
        ]
        home_branch = source_branch[
            source_branch.index("if (source === 'home')") :
            source_branch.index("if (source === 'calendar')")
        ]
        calendar_branch = source_branch[
            source_branch.index("if (source === 'calendar')") :
            source_branch.index(
                "} else if (document.referrer",
                source_branch.index("if (source === 'calendar')"),
            )
        ]

        self.assertIn("home_plan_refresh_marker", home_branch)
        self.assertNotIn("home_plan_refresh_marker", calendar_branch)
        self.assertIn("data.get('selected_date')", calendar_branch)
        self.assertIn(
            "{% url 'web_patient:health_calendar' %}",
            calendar_branch,
        )

    def test_glucose_detail_uses_real_label_and_context(self):
        HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BLOOD_GLUCOSE,
            value_main=Decimal("6.2"),
            measurement_context=MetricMeasurementContext.FASTING,
            measured_at=timezone.now(),
            source=MetricSource.MANUAL,
        )

        response = self.client.get(
            reverse("web_patient:health_record_detail"),
            {
                "type": "glucose",
                "title": "血糖",
                "source": "health_records",
            },
        )

        self.assertEqual(response.status_code, 200)
        record = response.context["records"][0]
        self.assertEqual(record["data"][0]["label"], "血糖")
        self.assertEqual(record["measurement_context"], MetricMeasurementContext.FASTING)
        self.assertContains(response, "(测量场景：空腹)")
        self.assertTrue(response.context["show_add_button"])

    def test_update_metric_rejects_other_patient_and_updates_glucose_context(self):
        metric = HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BLOOD_GLUCOSE,
            value_main=Decimal("6.2"),
            measurement_context=MetricMeasurementContext.FASTING,
            measured_at=timezone.now(),
            source=MetricSource.MANUAL,
        )
        other_user = CustomUser.objects.create_user(
            username="other_general_monitoring_patient",
            password="password",
            wx_openid="other_general_monitoring_openid",
        )
        other_patient = PatientProfile.objects.create(
            user=other_user,
            name="其他患者",
            phone="13800138888",
        )
        self.client.force_login(other_user)
        denied = self.client.post(
            reverse("web_patient:update_health_metric"),
            {
                "id": metric.id,
                "value_main": "7.0",
                "measurement_context": MetricMeasurementContext.RANDOM,
            },
        )
        self.assertFalse(denied.json()["success"])

        self.client.force_login(self.user)
        updated = self.client.post(
            reverse("web_patient:update_health_metric"),
            {
                "id": metric.id,
                "value_main": "7.0",
                "measurement_context": MetricMeasurementContext.RANDOM,
            },
        )
        self.assertTrue(updated.json()["success"])
        metric.refresh_from_db()
        self.assertEqual(metric.measurement_context, MetricMeasurementContext.RANDOM)

        rejected = self.client.post(
            reverse("web_patient:update_health_metric"),
            {
                "id": metric.id,
                "value_main": "-0.1",
                "measurement_context": MetricMeasurementContext.RANDOM,
            },
        )
        self.assertFalse(rejected.json()["success"])
        metric.refresh_from_db()
        self.assertEqual(metric.value_main, Decimal("7.00"))

    def test_patient_cannot_update_or_delete_device_metric(self):
        metric = HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BLOOD_KETONE,
            value_main=Decimal("0.8"),
            measured_at=timezone.now(),
            source=MetricSource.DEVICE,
        )

        update_response = self.client.post(
            reverse("web_patient:update_health_metric"),
            {"id": metric.id, "value_main": "0.4"},
        )
        delete_response = self.client.post(
            reverse("web_patient:delete_health_metric"),
            {"id": metric.id},
        )

        self.assertFalse(update_response.json()["success"])
        self.assertFalse(delete_response.json()["success"])
        metric.refresh_from_db()
        self.assertEqual(metric.value_main, Decimal("0.80"))
        self.assertTrue(metric.is_active)

    def test_patient_cannot_delete_another_patients_metric(self):
        other_patient = PatientProfile.objects.create(
            name="其他患者",
            phone="13800137777",
        )
        metric = HealthMetric.objects.create(
            patient=other_patient,
            metric_type=MetricType.URIC_ACID,
            value_main=Decimal("380"),
            measured_at=timezone.now(),
            source=MetricSource.MANUAL,
        )

        response = self.client.post(
            reverse("web_patient:delete_health_metric"),
            {"id": metric.id},
        )

        self.assertFalse(response.json()["success"])
        metric.refresh_from_db()
        self.assertTrue(metric.is_active)

    def test_patient_cannot_edit_an_old_manual_metric(self):
        metric = HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BLOOD_KETONE,
            value_main=Decimal("0.8"),
            measured_at=timezone.now() - timedelta(days=1),
            source=MetricSource.MANUAL,
        )

        response = self.client.post(
            reverse("web_patient:update_health_metric"),
            {"id": metric.id, "value_main": "0.4"},
        )

        self.assertFalse(response.json()["success"])
        metric.refresh_from_db()
        self.assertEqual(metric.value_main, Decimal("0.80"))


class GeneralMonitoringHomePlanTests(TestCase):
    def test_new_monitoring_plans_resolve_by_metric_type_and_keep_expected_order(self):
        plans = _build_daily_plans(
            [
                {"title": "旧标题一", "metric_type": MetricType.URIC_ACID, "status": 0},
                {"title": "旧标题二", "metric_type": MetricType.BLOOD_GLUCOSE, "status": 0},
                {"title": "旧标题三", "metric_type": MetricType.BLOOD_KETONE, "status": 0},
            ]
        )

        self.assertEqual(
            [item["type"] for item in plans],
            ["glucose", "ketone", "uric_acid"],
        )
        self.assertEqual(plans[0]["title"], "血糖监测")
