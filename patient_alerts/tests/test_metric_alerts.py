from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from health_data.models import (
    HealthMetric,
    MetricMeasurementContext,
    MetricSource,
    MetricType,
)
from patient_alerts.models import AlertEventType, AlertLevel, AlertStatus, PatientAlert, PatientAlertSource
from patient_alerts.services.metric_alerts import MetricAlertService
from users import choices
from users.models import CustomUser, DoctorProfile, PatientProfile


class MetricAlertServiceTests(TestCase):
    def setUp(self):
        self.doctor_user = CustomUser.objects.create_user(
            user_type=choices.UserType.DOCTOR,
            phone="13800138099",
            wx_nickname="Dr. Test",
        )
        self.doctor_profile = DoctorProfile.objects.create(
            user=self.doctor_user,
            name="测试医生",
            hospital="测试医院",
        )
        self.patient = PatientProfile.objects.create(
            phone="18600000099",
            name="测试患者",
            doctor=self.doctor_profile,
            baseline_blood_oxygen=98,
            baseline_weight=Decimal("60.0"),
            baseline_blood_pressure_sbp=120,
            baseline_blood_pressure_dbp=80,
        )

    def test_spo2_alert_created_for_mild(self):
        metric = HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BLOOD_OXYGEN,
            value_main=Decimal("94"),
            measured_at=timezone.now(),
            source=MetricSource.MANUAL,
        )

        alert = MetricAlertService.process_metric(metric)

        self.assertIsNotNone(alert)
        self.assertEqual(alert.event_type, AlertEventType.DATA)
        self.assertEqual(alert.event_level, AlertLevel.MILD)
        self.assertEqual(PatientAlert.objects.count(), 1)

    def test_spo2_alert_created_for_severe(self):
        metric = HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BLOOD_OXYGEN,
            value_main=Decimal("89"),
            measured_at=timezone.now(),
            source=MetricSource.MANUAL,
        )

        alert = MetricAlertService.process_metric(metric)

        self.assertIsNotNone(alert)
        self.assertEqual(alert.event_level, AlertLevel.SEVERE)

    def test_temperature_alert_for_72h_persistent_high(self):
        now = timezone.now()
        HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BODY_TEMPERATURE,
            value_main=Decimal("38.2"),
            measured_at=now - timedelta(hours=72),
            source=MetricSource.MANUAL,
        )
        metric = HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BODY_TEMPERATURE,
            value_main=Decimal("38.2"),
            measured_at=now,
            source=MetricSource.MANUAL,
        )

        alert = MetricAlertService.process_metric(metric)

        self.assertIsNotNone(alert)
        self.assertEqual(alert.event_level, AlertLevel.SEVERE)

    def test_temperature_alert_for_high_value(self):
        metric = HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BODY_TEMPERATURE,
            value_main=Decimal("39.5"),
            measured_at=timezone.now(),
            source=MetricSource.MANUAL,
        )

        alert = MetricAlertService.process_metric(metric)

        self.assertIsNotNone(alert)
        self.assertEqual(alert.event_level, AlertLevel.SEVERE)

    def test_weight_alert_when_change_over_3_days(self):
        now = timezone.now()
        HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.WEIGHT,
            value_main=Decimal("60.0"),
            measured_at=now - timedelta(days=2),
            source=MetricSource.MANUAL,
        )
        metric = HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.WEIGHT,
            value_main=Decimal("63.0"),
            measured_at=now,
            source=MetricSource.MANUAL,
        )

        alert = MetricAlertService.process_metric(metric)

        self.assertIsNotNone(alert)
        self.assertEqual(alert.event_level, AlertLevel.MILD)

    def test_weight_alert_when_change_over_180_days(self):
        metric = HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.WEIGHT,
            value_main=Decimal("64.0"),
            measured_at=timezone.now(),
            source=MetricSource.MANUAL,
        )

        alert = MetricAlertService.process_metric(metric)

        self.assertIsNotNone(alert)
        self.assertEqual(alert.event_level, AlertLevel.MILD)

    def test_blood_pressure_alert_created(self):
        metric = HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BLOOD_PRESSURE,
            value_main=Decimal("150"),
            value_sub=Decimal("100"),
            measured_at=timezone.now(),
            source=MetricSource.MANUAL,
        )

        alert = MetricAlertService.process_metric(metric)

        self.assertIsNotNone(alert)
        self.assertEqual(alert.event_level, AlertLevel.SEVERE)

    def test_blood_pressure_alert_for_mild_deviation(self):
        metric = HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BLOOD_PRESSURE,
            value_main=Decimal("132"),
            value_sub=Decimal("88"),
            measured_at=timezone.now(),
            source=MetricSource.MANUAL,
        )

        alert = MetricAlertService.process_metric(metric)

        self.assertIsNotNone(alert)
        self.assertEqual(alert.event_level, AlertLevel.MILD)

    def test_metric_alert_upgrades_instead_of_duplicate(self):
        time_now = timezone.now()
        metric_low = HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BLOOD_OXYGEN,
            value_main=Decimal("94"),
            measured_at=time_now - timedelta(hours=1),
            source=MetricSource.MANUAL,
        )
        MetricAlertService.process_metric(metric_low)

        metric_high = HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BLOOD_OXYGEN,
            value_main=Decimal("89"),
            measured_at=time_now,
            source=MetricSource.MANUAL,
        )
        MetricAlertService.process_metric(metric_high)

        alerts = PatientAlert.objects.filter(
            patient=self.patient,
            event_type=AlertEventType.DATA,
            event_title="血氧异常",
        )
        self.assertEqual(alerts.count(), 1)
        self.assertEqual(alerts.first().event_level, AlertLevel.SEVERE)

    def test_metric_alert_records_each_abnormal_metric_source(self):
        time_now = timezone.now()
        metric_first = HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BLOOD_PRESSURE,
            value_main=Decimal("150"),
            value_sub=Decimal("100"),
            measured_at=time_now - timedelta(hours=1),
            source=MetricSource.MANUAL,
        )
        MetricAlertService.process_metric(metric_first)

        metric_second = HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BLOOD_PRESSURE,
            value_main=Decimal("160"),
            value_sub=Decimal("105"),
            measured_at=time_now,
            source=MetricSource.MANUAL,
        )
        MetricAlertService.process_metric(metric_second)

        alert = PatientAlert.objects.get(
            patient=self.patient,
            event_type=AlertEventType.DATA,
            event_title="血压异常",
        )
        sources = PatientAlertSource.objects.filter(alert=alert).order_by("occurred_at")

        self.assertEqual(sources.count(), 2)
        self.assertEqual(sources[0].source_type, "metric")
        self.assertEqual(sources[0].source_id, metric_first.id)
        self.assertEqual(sources[0].source_key, f"metric:{metric_first.id}")
        self.assertEqual(sources[0].source_label, "血压")
        self.assertEqual(sources[0].value_display, "150/100")
        self.assertEqual(sources[0].baseline_display, "120/80")
        self.assertEqual(sources[0].event_level, AlertLevel.SEVERE)
        self.assertEqual(sources[1].source_id, metric_second.id)
        self.assertEqual(sources[1].value_display, "160/105")

    def test_metric_alert_after_completion_starts_new_source_group(self):
        time_now = timezone.now()
        metric_first = HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BLOOD_PRESSURE,
            value_main=Decimal("150"),
            value_sub=Decimal("100"),
            measured_at=time_now - timedelta(hours=1),
            source=MetricSource.MANUAL,
        )
        alert_first = MetricAlertService.process_metric(metric_first)
        alert_first.status = AlertStatus.COMPLETED
        alert_first.save(update_fields=["status"])

        metric_second = HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BLOOD_PRESSURE,
            value_main=Decimal("160"),
            value_sub=Decimal("105"),
            measured_at=time_now,
            source=MetricSource.MANUAL,
        )
        alert_second = MetricAlertService.process_metric(metric_second)

        self.assertNotEqual(alert_first.id, alert_second.id)
        self.assertEqual(PatientAlertSource.objects.filter(alert=alert_first).count(), 1)
        self.assertEqual(PatientAlertSource.objects.filter(alert=alert_second).count(), 1)

    def test_spo2_confirmed_drop_promotes_level(self):
        time_now = timezone.now()
        metric_first = HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BLOOD_OXYGEN,
            value_main=Decimal("93"),
            measured_at=time_now - timedelta(hours=1),
            source=MetricSource.MANUAL,
        )
        alert_first = MetricAlertService.process_metric(metric_first)
        self.assertIsNotNone(alert_first)
        self.assertEqual(alert_first.event_level, AlertLevel.MILD)

        metric_second = HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BLOOD_OXYGEN,
            value_main=Decimal("93"),
            measured_at=time_now,
            source=MetricSource.MANUAL,
        )
        alert_second = MetricAlertService.process_metric(metric_second)
        self.assertIsNotNone(alert_second)
        self.assertEqual(alert_second.event_level, AlertLevel.MODERATE)

    def test_new_general_monitoring_metrics_create_expected_alerts(self):
        cases = [
            (
                MetricType.BLOOD_GLUCOSE,
                Decimal("7.0"),
                MetricMeasurementContext.FASTING,
                AlertLevel.MILD,
                "血糖异常",
            ),
            (
                MetricType.BLOOD_KETONE,
                Decimal("1.51"),
                None,
                AlertLevel.MODERATE,
                "血酮异常",
            ),
            (
                MetricType.URIC_ACID,
                Decimal("420.01"),
                None,
                AlertLevel.MILD,
                "尿酸异常",
            ),
        ]

        for metric_type, value, context, level, title in cases:
            with self.subTest(metric_type=metric_type):
                metric = HealthMetric.objects.create(
                    patient=self.patient,
                    metric_type=metric_type,
                    value_main=value,
                    measurement_context=context,
                    measured_at=timezone.now(),
                    source=MetricSource.MANUAL,
                )
                alert = MetricAlertService.process_metric(metric)

                self.assertIsNotNone(alert)
                self.assertEqual(alert.event_level, level)
                self.assertEqual(alert.event_title, title)
                source = PatientAlertSource.objects.get(source_key=f"metric:{metric.id}")
                self.assertEqual(
                    source.source_payload.get("measurement_context"),
                    context,
                )

    def test_metric_edit_to_normal_removes_source_and_deactivates_alert(self):
        metric = HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BLOOD_GLUCOSE,
            value_main=Decimal("8.0"),
            measurement_context=MetricMeasurementContext.FASTING,
            measured_at=timezone.now(),
            source=MetricSource.MANUAL,
        )
        alert = MetricAlertService.process_metric(metric)
        self.assertTrue(alert.is_active)

        metric.value_main = Decimal("6.0")
        metric.save(update_fields=["value_main"])
        result = MetricAlertService.process_metric(metric)

        self.assertIsNone(result)
        self.assertFalse(PatientAlertSource.objects.filter(source_key=f"metric:{metric.id}").exists())
        alert.refresh_from_db()
        self.assertFalse(alert.is_active)

    def test_remove_metric_recomputes_parent_from_remaining_sources(self):
        older = HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BLOOD_KETONE,
            value_main=Decimal("0.6"),
            measured_at=timezone.now() - timedelta(hours=1),
            source=MetricSource.MANUAL,
        )
        newer = HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BLOOD_KETONE,
            value_main=Decimal("3.1"),
            measured_at=timezone.now(),
            source=MetricSource.MANUAL,
        )
        alert = MetricAlertService.process_metric(older)
        MetricAlertService.process_metric(newer)

        MetricAlertService.remove_metric(newer)
        alert.refresh_from_db()
        self.assertTrue(alert.is_active)
        self.assertEqual(alert.event_level, AlertLevel.MILD)
        self.assertEqual(alert.event_time, older.measured_at)

        MetricAlertService.remove_metric(older)
        alert.refresh_from_db()
        self.assertFalse(alert.is_active)
