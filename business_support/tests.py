import hashlib
import json
from datetime import datetime
from decimal import Decimal

from django.contrib import admin
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from business_support.admin.device import DeviceAdmin
from business_support.models import Device
from health_data.models import HealthMetric, MetricSource, MetricType
from users.models import PatientProfile


def _signed_headers(body: bytes, app_secret: str, curtime: str = "1765348624") -> dict:
    body_md5 = hashlib.md5(body).hexdigest()
    checksum = hashlib.sha1(f"{app_secret}{body_md5}{curtime}".encode("utf-8")).hexdigest()
    return {
        "HTTP_MD5": body_md5,
        "HTTP_CHECKSUM": checksum,
        "HTTP_CURTIME": curtime,
    }


def _hrt_body(payload: dict) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


class HrtDeviceProviderAdminTests(TestCase):
    def test_hrt_provider_is_seeded_and_device_admin_exposes_provider(self):
        from business_support.admin.device_provider import DeviceProviderAdmin
        from business_support.models import DeviceProvider

        provider = DeviceProvider.objects.get(code="HRT")

        self.assertEqual(provider.name, "HRT")
        self.assertTrue(provider.is_active)
        self.assertIn("provider", DeviceAdmin.list_display)
        self.assertIn("provider", DeviceAdmin.list_filter)
        self.assertIsInstance(admin.site._registry[DeviceProvider], DeviceProviderAdmin)


class HrtCallbackAdapterTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.record_time_ms = 1765348624000
        self.body = _hrt_body(
            {
                "eventType": 1,
                "data": {
                    "type": "BPG",
                    "deviceNo": "IMEI-HRT-001",
                    "recordTime": self.record_time_ms,
                    "bpgData": {"sbp": 121, "dbp": 79, "hr": 73},
                },
            }
        )

    @override_settings(SMARTWATCH_CONFIG={"APP_KEY": "app-key", "APP_SECRET": "hrt-secret", "API_BASE_URL": "https://example.test"})
    def test_verify_signature_accepts_valid_hrt_headers(self):
        from business_support.services.device_integrations.hrt import HrtCallbackAdapter

        request = self.factory.post(
            "/deviceupload",
            data=self.body,
            content_type="application/json",
            **_signed_headers(self.body, "hrt-secret"),
        )

        self.assertTrue(HrtCallbackAdapter().verify_signature(request))

    @override_settings(SMARTWATCH_CONFIG={"APP_KEY": "app-key", "APP_SECRET": "hrt-secret", "API_BASE_URL": "https://example.test"})
    def test_parse_body_converts_bpg_payload_to_standard_readings(self):
        from business_support.services.device_integrations.hrt import HrtCallbackAdapter

        result = HrtCallbackAdapter().parse_body(self.body)

        self.assertEqual(result.provider_code, "HRT")
        self.assertEqual(result.raw_event_type, 1)
        self.assertEqual(len(result.readings), 2)
        bp, hr = result.readings
        self.assertEqual(bp.provider_code, "HRT")
        self.assertEqual(bp.device_no, "IMEI-HRT-001")
        self.assertEqual(bp.metric_type, MetricType.BLOOD_PRESSURE)
        self.assertEqual(bp.value_main, Decimal("121"))
        self.assertEqual(bp.value_sub, Decimal("79"))
        self.assertEqual(hr.metric_type, MetricType.HEART_RATE)
        self.assertEqual(hr.value_main, Decimal("73"))
        self.assertIsNone(hr.value_sub)
        self.assertTrue(timezone.is_aware(bp.measured_at))

    def test_parse_body_ignores_non_metric_event_types(self):
        from business_support.services.device_integrations.hrt import HrtCallbackAdapter

        body = _hrt_body({"eventType": 9, "data": {"type": "BPG"}})

        result = HrtCallbackAdapter().parse_body(body)

        self.assertEqual(result.provider_code, "HRT")
        self.assertEqual(result.raw_event_type, 9)
        self.assertEqual(result.readings, [])

    def test_legacy_smartwatch_service_alias_is_not_exposed(self):
        import business_support.service.device as device_service

        self.assertFalse(hasattr(device_service, "SmartWatchService"))


class DeviceMetricIngestionTests(TestCase):
    def setUp(self):
        from business_support.models import DeviceProvider

        self.provider = DeviceProvider.objects.get(code="HRT")
        self.patient = PatientProfile.objects.create(phone="13900001000", name="HRT患者")
        self.device = Device.objects.create(
            provider=self.provider,
            sn="SN-HRT-INGEST-001",
            imei="IMEI-HRT-INGEST-001",
            current_patient=self.patient,
        )
        self.measured_at = timezone.make_aware(datetime(2025, 12, 10, 9, 17))

    def test_ingest_standard_reading_creates_device_metric_and_touches_device(self):
        from business_support.services.device_integrations.base import DeviceMetricReading
        from health_data.services.device_metric_ingestion import DeviceMetricIngestionService

        reading = DeviceMetricReading(
            provider_code="HRT",
            device_no=self.device.imei,
            measured_at=self.measured_at,
            metric_type=MetricType.BLOOD_OXYGEN,
            value_main=Decimal("96"),
            raw_payload={"spo": {"agvOxy": 96}},
        )

        result = DeviceMetricIngestionService.ingest_readings([reading])

        self.assertEqual(result.created_count, 1)
        self.assertEqual(result.skipped_count, 0)
        metric = HealthMetric.objects.get(patient=self.patient, metric_type=MetricType.BLOOD_OXYGEN)
        self.assertEqual(metric.source, MetricSource.DEVICE)
        self.assertEqual(metric.value_main, Decimal("96"))
        self.assertEqual(metric.measured_at, self.measured_at)
        self.device.refresh_from_db()
        self.assertEqual(self.device.last_active_at, self.measured_at)

    def test_ingest_skips_inactive_device_without_creating_metric(self):
        from business_support.services.device_integrations.base import DeviceMetricReading
        from health_data.services.device_metric_ingestion import DeviceMetricIngestionService

        self.device.is_active = False
        self.device.save(update_fields=["is_active"])
        reading = DeviceMetricReading(
            provider_code="HRT",
            device_no=self.device.imei,
            measured_at=self.measured_at,
            metric_type=MetricType.WEIGHT,
            value_main=Decimal("68.30"),
        )

        result = DeviceMetricIngestionService.ingest_readings([reading])

        self.assertEqual(result.created_count, 0)
        self.assertEqual(result.skipped_count, 1)
        self.assertFalse(HealthMetric.objects.filter(patient=self.patient).exists())


class HrtDeviceCallbackViewTests(TestCase):
    def setUp(self):
        from business_support.models import DeviceProvider

        self.provider = DeviceProvider.objects.get(code="HRT")
        self.patient = PatientProfile.objects.create(phone="13900002000", name="HRT回调患者")
        self.device = Device.objects.create(
            provider=self.provider,
            sn="SN-HRT-CALLBACK-001",
            imei="IMEI-HRT-CALLBACK-001",
            current_patient=self.patient,
        )

    @override_settings(SMARTWATCH_CONFIG={"APP_KEY": "app-key", "APP_SECRET": "hrt-secret", "API_BASE_URL": "https://example.test"})
    def test_deviceupload_root_uses_hrt_adapter_and_business_ingestion(self):
        body = _hrt_body(
            {
                "eventType": 1,
                "data": {
                    "type": "WATCH",
                    "deviceNo": self.device.imei,
                    "recordTime": 1765348624000,
                    "watchData": {
                        "spo": {"agvOxy": 95},
                        "pedo": {"step": 1234},
                    },
                },
            }
        )

        response = self.client.post(
            reverse("device_upload_root"),
            data=body,
            content_type="application/json",
            **_signed_headers(body, "hrt-secret"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"errorCode": 0, "msg": "success"})
        metrics = HealthMetric.objects.filter(patient=self.patient).order_by("metric_type")
        self.assertEqual(metrics.count(), 2)
        self.assertSetEqual(
            set(metrics.values_list("metric_type", flat=True)),
            {MetricType.BLOOD_OXYGEN, MetricType.STEPS},
        )


class HrtDeviceCallbackIntegrationTests(TestCase):
    def setUp(self):
        from business_support.models import DeviceProvider

        self.provider = DeviceProvider.objects.get(code="HRT")
        self.patient = PatientProfile.objects.create(phone="13900003000", name="HRT全量指标患者")
        self.device = Device.objects.create(
            provider=self.provider,
            sn="SN-HRT-INTEGRATION-001",
            imei="IMEI-HRT-INTEGRATION-001",
            current_patient=self.patient,
        )

    @override_settings(SMARTWATCH_CONFIG={"APP_KEY": "app-key", "APP_SECRET": "hrt-secret", "API_BASE_URL": "https://example.test"})
    def test_hrt_callback_persists_every_supported_metric_type(self):
        payloads = [
            {
                "eventType": 1,
                "data": {
                    "type": "BPG",
                    "deviceNo": self.device.imei,
                    "recordTime": 1765348624000,
                    "bpgData": {"sbp": 118, "dbp": 76, "hr": 71},
                },
            },
            {
                "eventType": 1,
                "data": {
                    "type": "WATCH",
                    "deviceNo": self.device.imei,
                    "recordTime": 1765348684000,
                    "watchData": {
                        "spo": {"agvOxy": 96},
                        "pedo": {"step": 2345},
                    },
                },
            },
            {
                "eventType": 1,
                "data": {
                    "type": "WS",
                    "deviceNo": self.device.imei,
                    "recordTime": 1765348744000,
                    "wsData": {"weight": 6830},
                },
            }
        ]

        for payload in payloads:
            body = _hrt_body(payload)
            response = self.client.post(
                reverse("device_upload_root"),
                data=body,
                content_type="application/json",
                **_signed_headers(body, "hrt-secret"),
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"errorCode": 0, "msg": "success"})

        metrics = {
            metric.metric_type: metric
            for metric in HealthMetric.objects.filter(patient=self.patient)
        }

        self.assertSetEqual(
            set(metrics),
            {
                MetricType.BLOOD_PRESSURE,
                MetricType.HEART_RATE,
                MetricType.BLOOD_OXYGEN,
                MetricType.STEPS,
                MetricType.WEIGHT,
            },
        )
        self.assertEqual(metrics[MetricType.BLOOD_PRESSURE].value_main, Decimal("118"))
        self.assertEqual(metrics[MetricType.BLOOD_PRESSURE].value_sub, Decimal("76"))
        self.assertEqual(metrics[MetricType.HEART_RATE].value_main, Decimal("71"))
        self.assertEqual(metrics[MetricType.BLOOD_OXYGEN].value_main, Decimal("96"))
        self.assertEqual(metrics[MetricType.STEPS].value_main, Decimal("2345"))
        self.assertEqual(metrics[MetricType.WEIGHT].value_main, Decimal("68.3"))


class HealthMetricProviderPayloadBoundaryTests(TestCase):
    def test_health_metric_service_does_not_parse_provider_payloads(self):
        from health_data.services.health_metric import HealthMetricService

        self.assertFalse(hasattr(HealthMetricService, "handle_payload"))
