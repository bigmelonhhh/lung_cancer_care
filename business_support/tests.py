import hashlib
import json
import struct
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import patch

from django.contrib import admin
from django.db import connection
from django.test import Client, RequestFactory, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
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


def _proto_varint(value: int) -> bytes:
    encoded = bytearray()
    while value > 0x7F:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _proto_varint_field(field_number: int, value: int) -> bytes:
    return _proto_varint(field_number << 3) + _proto_varint(value)


def _proto_fixed32_field(field_number: int, value: int) -> bytes:
    return _proto_varint((field_number << 3) | 5) + struct.pack("<I", value)


def _proto_message_field(field_number: int, payload: bytes) -> bytes:
    return (
        _proto_varint((field_number << 3) | 2)
        + _proto_varint(len(payload))
        + payload
    )


def _iwown_datetime_payload(measured_at: datetime) -> bytes:
    wall_clock_seconds = int(measured_at.replace(tzinfo=UTC).timestamp())
    rt_time = _proto_fixed32_field(1, wall_clock_seconds)
    return _proto_message_field(1, rt_time) + _proto_fixed32_field(2, 8 * 3600)


def _iwown_packet(option: int, payload: bytes, *, prefix: bytes = b"DT") -> bytes:
    return prefix + struct.pack("<HHH", len(payload), 0, option) + payload


def _iwown_body(device_id: str, *packets: bytes) -> bytes:
    encoded_device_id = device_id.encode("ascii")
    if len(encoded_device_id) != 15:
        raise ValueError("IWOWN device ID must be exactly 15 bytes")
    return encoded_device_id + b"".join(packets)


def _iwown_five_metric_body(device_id: str) -> bytes:
    steps_measured_at = datetime(2026, 7, 18, 10, 30, 0)
    steps_report = _proto_message_field(
        5, _proto_fixed32_field(1, 5432)
    ) + _proto_message_field(6, _iwown_datetime_payload(steps_measured_at))

    health_measured_at = datetime(2026, 7, 18, 10, 31, 0)
    heart_rate = (
        _proto_fixed32_field(1, 60)
        + _proto_fixed32_field(2, 86)
        + _proto_fixed32_field(3, 72)
    )
    blood_pressure = _proto_fixed32_field(1, 120) + _proto_fixed32_field(2, 78)
    blood_oxygen = (
        _proto_fixed32_field(1, 94)
        + _proto_fixed32_field(2, 99)
        + _proto_fixed32_field(3, 96)
    )
    health = (
        _proto_message_field(1, _iwown_datetime_payload(health_measured_at))
        + _proto_message_field(4, heart_rate)
        + _proto_message_field(6, blood_pressure)
        + _proto_message_field(12, blood_oxygen)
    )
    health_history = _proto_fixed32_field(1, 21) + _proto_message_field(3, health)
    health_notification = _proto_varint_field(1, 0) + _proto_message_field(
        4, health_history
    )

    weight_measured_at = datetime(2026, 7, 18, 10, 32, 0)
    scale = (
        _proto_fixed32_field(1, 68)
        + _proto_fixed32_field(2, 500)
        + _proto_fixed32_field(3, 0)
        + _proto_fixed32_field(4, 22)
        + _proto_message_field(5, _iwown_datetime_payload(weight_measured_at))
    )
    third_party_health = (
        _proto_message_field(1, b"IWOWN SCALE")
        + _proto_message_field(2, b"AA:BB:CC:DD:EE:FF")
        + _proto_fixed32_field(3, 1)
        + _proto_fixed32_field(4, 1)
        + _proto_message_field(6, scale)
    )
    third_party = _proto_message_field(1, third_party_health)
    weight_history = _proto_fixed32_field(1, 22) + _proto_message_field(
        16, third_party
    )
    weight_notification = _proto_varint_field(1, 14) + _proto_message_field(
        4, weight_history
    )

    return _iwown_body(
        device_id,
        _iwown_packet(0x0A, steps_report),
        _iwown_packet(0x80, health_notification),
        _iwown_packet(0x80, weight_notification),
    )


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

    def test_iwown_provider_is_seeded_and_can_be_assigned_to_device(self):
        from business_support.models import DeviceProvider

        provider = DeviceProvider.objects.filter(code="IWOWN").first()

        self.assertIsNotNone(provider)
        device = Device.objects.create(
            provider=provider,
            sn="SN-IWOWN-PROVIDER-001",
            imei="860132060872223",
        )

        self.assertEqual(provider.name, "IWOWN")
        self.assertTrue(provider.is_active)
        self.assertEqual(device.provider, provider)


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


class IwownDeviceInfoCallbackTests(TestCase):
    def test_device_info_upload_accepts_raw_json_and_logs_allowlisted_metadata(self):
        payload = {
            "deviceid": "860132060872223",
            "imsi": "460016757635120",
            "sn": "IWOWN-SN-001",
            "model": "H102CN",
            "version": "54.2.0.6",
            "sim1_iccid": "89860123801275636995",
            "watch_event": 2,
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        client = Client(enforce_csrf_checks=True)
        upload_url = reverse("iwown_device_info_upload")

        self.assertEqual(upload_url, "/deviceupload/iwown/deviceinfo/upload")

        with self.assertLogs(
            "business_support.services.device_integrations.iwown",
            level="INFO",
        ) as captured:
            response = client.post(
                upload_url,
                data=body,
                content_type="application/x-www-form-urlencoded",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ReturnCode": 0})
        log_record = captured.records[-1]
        self.assertEqual(log_record.msg["event"], "iwown_device_info_received")
        self.assertEqual(log_record.msg["provider"], "IWOWN")
        self.assertEqual(log_record.msg["body_bytes"], len(body))
        self.assertEqual(log_record.msg["content_type"], "application/x-www-form-urlencoded")
        self.assertIn("device_id_hash", log_record.msg)
        self.assertEqual(
            log_record.msg["device_id_hash"],
            hashlib.sha256(payload["deviceid"].encode("utf-8")).hexdigest(),
        )
        self.assertEqual(log_record.msg["device_id_suffix"], "2223")
        self.assertNotIn("device_id", log_record.msg)
        self.assertEqual(
            log_record.msg["device_info"],
            {
                "model": payload["model"],
                "version": payload["version"],
                "watch_event": payload["watch_event"],
            },
        )
        self.assertNotIn("imsi", log_record.msg["device_info"])
        self.assertNotIn("sim1_iccid", log_record.msg["device_info"])
        self.assertEqual(log_record.msg["payload_keys"], sorted(payload))

    def test_device_info_upload_rejects_non_post_method(self):
        response = self.client.get(reverse("iwown_device_info_upload"))

        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.json(), {"ReturnCode": 10002})

    def test_device_info_upload_logs_metadata_only_when_json_is_invalid(self):
        body = b"\xff\xfeIWOWN invalid device info"

        with self.assertLogs(
            "business_support.services.device_integrations.iwown",
            level="WARNING",
        ) as captured:
            response = self.client.post(
                reverse("iwown_device_info_upload"),
                data=body,
                content_type="application/x-www-form-urlencoded",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ReturnCode": 10002})
        log_record = captured.records[-1]
        self.assertEqual(log_record.msg["event"], "iwown_device_info_invalid")
        self.assertEqual(log_record.msg["provider"], "IWOWN")
        self.assertEqual(log_record.msg["body_bytes"], len(body))
        self.assertIn("body_sha256", log_record.msg)
        self.assertEqual(log_record.msg["body_sha256"], hashlib.sha256(body).hexdigest())
        self.assertNotIn("body_text_preview", log_record.msg)
        self.assertNotIn("body_hex_preview", log_record.msg)

    def test_device_info_upload_rejects_oversized_json_without_logging_raw_body(self):
        body = json.dumps({"padding": "x" * (64 * 1024)}).encode("utf-8")

        with self.assertLogs(
            "business_support.services.device_integrations.iwown",
            level="WARNING",
        ) as captured:
            response = self.client.post(
                reverse("iwown_device_info_upload"),
                data=body,
                content_type="application/x-www-form-urlencoded",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ReturnCode": 10002})
        log_record = captured.records[-1]
        self.assertIn("too large", log_record.msg["error"])
        self.assertIn("body_sha256", log_record.msg)
        self.assertEqual(log_record.msg["body_sha256"], hashlib.sha256(body).hexdigest())
        self.assertNotIn("body_text_preview", log_record.msg)
        self.assertNotIn("body_hex_preview", log_record.msg)


class IwownHealthDataAdapterTests(TestCase):
    device_id = "860132060872223"

    def test_parse_current_day_steps_packet(self):
        from business_support.services.device_integrations.iwown import (
            IwownHealthDataAdapter,
        )

        measured_at = datetime(2026, 7, 18, 10, 30, 0)
        realtime_health = _proto_fixed32_field(1, 4321)
        report = _proto_message_field(5, realtime_health) + _proto_message_field(
            6,
            _iwown_datetime_payload(measured_at),
        )
        body = _iwown_body(self.device_id, _iwown_packet(0x0A, report))

        result = IwownHealthDataAdapter().parse_body(body)

        self.assertEqual(result.provider_code, "IWOWN")
        self.assertEqual(result.raw_event_type, "0x0A")
        self.assertEqual(len(result.readings), 1)
        reading = result.readings[0]
        self.assertEqual(reading.device_no, self.device_id)
        self.assertEqual(reading.metric_type, MetricType.STEPS)
        self.assertEqual(reading.value_main, Decimal("4321"))
        self.assertTrue(reading.external_event_id.startswith("0x0A:"))
        self.assertEqual(
            reading.measured_at,
            timezone.make_aware(measured_at, timezone.get_current_timezone()),
        )

    def test_parse_historical_health_maps_hr_bp_and_oxygen_only(self):
        from business_support.services.device_integrations.iwown import (
            IwownHealthDataAdapter,
        )

        measured_at = datetime(2026, 7, 18, 10, 31, 0)
        pedometer = (
            _proto_fixed32_field(1, 1)
            + _proto_fixed32_field(2, 1)
            + _proto_fixed32_field(3, 120)
            + _proto_fixed32_field(4, 99)
            + _proto_fixed32_field(5, 450)
        )
        heart_rate = (
            _proto_fixed32_field(1, 61)
            + _proto_fixed32_field(2, 89)
            + _proto_fixed32_field(3, 73)
        )
        blood_pressure = _proto_fixed32_field(1, 121) + _proto_fixed32_field(
            2, 79
        )
        blood_oxygen = (
            _proto_fixed32_field(1, 94)
            + _proto_fixed32_field(2, 99)
            + _proto_fixed32_field(3, 97)
        )
        ignored_temperature = (
            _proto_varint_field(1, 1)
            + _proto_fixed32_field(2, 365)
            + _proto_fixed32_field(3, 366)
        )
        health = (
            _proto_message_field(1, _iwown_datetime_payload(measured_at))
            + _proto_message_field(3, pedometer)
            + _proto_message_field(4, heart_rate)
            + _proto_message_field(6, blood_pressure)
            + _proto_message_field(12, blood_oxygen)
            + _proto_message_field(13, ignored_temperature)
        )
        history_data = _proto_fixed32_field(1, 17) + _proto_message_field(3, health)
        notification = _proto_varint_field(1, 0) + _proto_message_field(
            4, history_data
        )
        body = _iwown_body(
            self.device_id,
            _iwown_packet(0x80, notification),
        )

        result = IwownHealthDataAdapter().parse_body(body)

        readings = {reading.metric_type: reading for reading in result.readings}
        self.assertSetEqual(
            set(readings),
            {
                MetricType.HEART_RATE,
                MetricType.BLOOD_PRESSURE,
                MetricType.BLOOD_OXYGEN,
            },
        )
        self.assertEqual(readings[MetricType.HEART_RATE].value_main, Decimal("73"))
        self.assertEqual(
            readings[MetricType.BLOOD_PRESSURE].value_main,
            Decimal("121"),
        )
        self.assertEqual(
            readings[MetricType.BLOOD_PRESSURE].value_sub,
            Decimal("79"),
        )
        self.assertEqual(
            readings[MetricType.BLOOD_OXYGEN].value_main,
            Decimal("97"),
        )
        event_ids = {reading.external_event_id for reading in result.readings}
        self.assertEqual(len(event_ids), 1)
        self.assertTrue(next(iter(event_ids)).startswith("0x80:0:17:"))
        self.assertNotIn(MetricType.STEPS, readings)

    def test_parse_third_party_packet_maps_only_supported_metrics(self):
        from business_support.services.device_integrations.iwown import (
            IwownHealthDataAdapter,
        )

        measured_at = datetime(2026, 7, 18, 10, 32, 0)
        date_time = _iwown_datetime_payload(measured_at)
        blood_pressure = (
            _proto_fixed32_field(1, 119)
            + _proto_fixed32_field(2, 77)
            + _proto_fixed32_field(3, 72)
            + _proto_fixed32_field(4, 71)
            + _proto_message_field(5, date_time)
            + _proto_varint_field(6, 0)
        )
        scale = (
            _proto_fixed32_field(1, 68)
            + _proto_fixed32_field(2, 501)
            + _proto_fixed32_field(3, 0)
            + _proto_fixed32_field(4, 23)
            + _proto_message_field(5, date_time)
        )
        blood_oxygen = (
            _proto_fixed32_field(1, 74)
            + _proto_fixed32_field(2, 96)
            + _proto_fixed32_field(3, 7)
            + _proto_message_field(4, date_time)
        )
        ignored_temperature = _proto_fixed32_field(
            1, 367
        ) + _proto_message_field(2, date_time)
        third_party_health = (
            _proto_message_field(1, b"IWOWN SCALE")
            + _proto_message_field(2, b"AA:BB:CC:DD:EE:FF")
            + _proto_fixed32_field(3, 1)
            + _proto_fixed32_field(4, 1)
            + _proto_message_field(5, blood_pressure)
            + _proto_message_field(6, scale)
            + _proto_message_field(7, blood_oxygen)
            + _proto_message_field(8, ignored_temperature)
        )
        third_party = _proto_message_field(1, third_party_health)
        history_data = _proto_fixed32_field(1, 18) + _proto_message_field(
            16, third_party
        )
        notification = _proto_varint_field(1, 14) + _proto_message_field(
            4, history_data
        )
        body = _iwown_body(self.device_id, _iwown_packet(0x80, notification))

        result = IwownHealthDataAdapter().parse_body(body)

        readings = {reading.metric_type: reading for reading in result.readings}
        self.assertSetEqual(
            set(readings),
            {
                MetricType.HEART_RATE,
                MetricType.BLOOD_PRESSURE,
                MetricType.BLOOD_OXYGEN,
                MetricType.WEIGHT,
            },
        )
        self.assertEqual(readings[MetricType.HEART_RATE].value_main, Decimal("72"))
        self.assertEqual(
            readings[MetricType.BLOOD_PRESSURE].value_main,
            Decimal("119"),
        )
        self.assertEqual(
            readings[MetricType.BLOOD_PRESSURE].value_sub,
            Decimal("77"),
        )
        self.assertEqual(
            readings[MetricType.BLOOD_OXYGEN].value_main,
            Decimal("96"),
        )
        self.assertEqual(readings[MetricType.WEIGHT].value_main, Decimal("68"))
        event_ids = {reading.external_event_id for reading in result.readings}
        self.assertEqual(len(event_ids), 1)
        self.assertTrue(next(iter(event_ids)).startswith("0x80:14:18:"))


class IwownHealthDataCallbackTests(TestCase):
    device_id = "860132060872223"

    def setUp(self):
        from business_support.models import DeviceProvider

        self.provider = DeviceProvider.objects.get(code="IWOWN")
        self.patient = PatientProfile.objects.create(
            phone="13900004000",
            name="埃微回调患者",
        )
        self.device = Device.objects.create(
            provider=self.provider,
            sn="SN-IWOWN-CALLBACK-001",
            imei=self.device_id,
            current_patient=self.patient,
        )

    def test_pb_upload_persists_all_five_supported_metrics(self):
        upload_url = reverse("iwown_health_data_upload")
        body = _iwown_five_metric_body(self.device_id)

        self.assertEqual(upload_url, "/deviceupload/iwown/pb/upload")

        with self.assertLogs(
            "business_support.services.device_integrations.iwown",
            level="INFO",
        ) as captured:
            response = self.client.post(
                upload_url,
                data=body,
                content_type="application/x-www-form-urlencoded",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"\x00")
        metrics = {
            metric.metric_type: metric
            for metric in HealthMetric.objects.filter(patient=self.patient)
        }
        self.assertSetEqual(
            set(metrics),
            {
                MetricType.STEPS,
                MetricType.HEART_RATE,
                MetricType.BLOOD_PRESSURE,
                MetricType.BLOOD_OXYGEN,
                MetricType.WEIGHT,
            },
        )
        self.assertTrue(
            all(metric.source == MetricSource.DEVICE for metric in metrics.values())
        )
        self.assertEqual(metrics[MetricType.STEPS].value_main, Decimal("5432"))
        self.assertEqual(metrics[MetricType.HEART_RATE].value_main, Decimal("72"))
        self.assertEqual(
            metrics[MetricType.BLOOD_PRESSURE].value_main,
            Decimal("120"),
        )
        self.assertEqual(
            metrics[MetricType.BLOOD_PRESSURE].value_sub,
            Decimal("78"),
        )
        self.assertEqual(
            metrics[MetricType.BLOOD_OXYGEN].value_main,
            Decimal("96"),
        )
        self.assertEqual(metrics[MetricType.WEIGHT].value_main, Decimal("68"))
        self.device.refresh_from_db()
        self.assertIsNotNone(self.device.last_active_at)
        log_record = captured.records[-1]
        self.assertEqual(log_record.msg["event"], "iwown_health_data_received")
        self.assertEqual(
            log_record.msg["device_id_hash"],
            hashlib.sha256(self.device_id.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(log_record.msg["device_id_suffix"], "2223")
        self.assertNotIn("device_id", log_record.msg)
        self.assertEqual(log_record.msg["reading_count"], 5)
        self.assertEqual(log_record.msg["created_count"], 5)
        self.assertEqual(log_record.msg["skipped_count"], 0)
        self.assertNotIn("body", log_record.msg)

    def test_pb_upload_returns_iwown_error_bytes_for_malformed_packets(self):
        upload_url = reverse("iwown_health_data_upload")
        invalid_prefix = _iwown_body(
            self.device_id,
            _iwown_packet(0x0A, b"", prefix=b"XX"),
        )
        truncated_payload = (
            self.device_id.encode("ascii")
            + b"DT"
            + struct.pack("<HHH", 8, 0, 0x0A)
            + b"\x00"
        )

        prefix_response = self.client.post(
            upload_url,
            data=invalid_prefix,
            content_type="application/x-www-form-urlencoded",
        )
        length_response = self.client.post(
            upload_url,
            data=truncated_payload,
            content_type="application/x-www-form-urlencoded",
        )
        method_response = self.client.get(upload_url)

        self.assertEqual(prefix_response.status_code, 200)
        self.assertEqual(prefix_response.content, b"\x03")
        self.assertEqual(length_response.status_code, 200)
        self.assertEqual(length_response.content, b"\x02")
        self.assertEqual(method_response.status_code, 405)
        self.assertEqual(method_response.content, b"\x02")
        self.assertFalse(HealthMetric.objects.filter(patient=self.patient).exists())

    def test_pb_upload_rejects_historical_metric_without_required_timestamp(self):
        heart_rate = (
            _proto_fixed32_field(1, 60)
            + _proto_fixed32_field(2, 86)
            + _proto_fixed32_field(3, 72)
        )
        health_without_timestamp = _proto_message_field(4, heart_rate)
        history_data = _proto_fixed32_field(1, 23) + _proto_message_field(
            3, health_without_timestamp
        )
        notification = _proto_varint_field(1, 0) + _proto_message_field(
            4, history_data
        )

        response = self.client.post(
            reverse("iwown_health_data_upload"),
            data=_iwown_body(
                self.device_id,
                _iwown_packet(0x80, notification),
            ),
            content_type="application/x-www-form-urlencoded",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"\x02")
        self.assertFalse(HealthMetric.objects.filter(patient=self.patient).exists())

    def test_pb_upload_acknowledges_unbound_device_without_writing_patient_data(self):
        self.device.current_patient = None
        self.device.save(update_fields=["current_patient"])

        response = self.client.post(
            reverse("iwown_health_data_upload"),
            data=_iwown_five_metric_body(self.device_id),
            content_type="application/x-www-form-urlencoded",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"\x00")
        self.assertFalse(HealthMetric.objects.exists())
        self.device.refresh_from_db()
        self.assertIsNone(self.device.last_active_at)

    def test_pb_upload_does_not_regress_current_day_steps(self):
        from business_support.models import DeviceMetricReceipt

        first_response = self.client.post(
            reverse("iwown_health_data_upload"),
            data=_iwown_five_metric_body(self.device_id),
            content_type="application/x-www-form-urlencoded",
        )
        later_time = datetime(2026, 7, 18, 11, 0, 0)
        lower_steps_report = _proto_message_field(
            5, _proto_fixed32_field(1, 5000)
        ) + _proto_message_field(6, _iwown_datetime_payload(later_time))
        second_response = self.client.post(
            reverse("iwown_health_data_upload"),
            data=_iwown_body(
                self.device_id,
                _iwown_packet(0x0A, lower_steps_report),
            ),
            content_type="application/x-www-form-urlencoded",
        )

        self.assertEqual(first_response.content, b"\x00")
        self.assertEqual(second_response.content, b"\x00")
        steps = HealthMetric.objects.get(
            patient=self.patient,
            metric_type=MetricType.STEPS,
        )
        self.assertEqual(steps.value_main, Decimal("5432"))
        self.assertEqual(
            DeviceMetricReceipt.objects.filter(device=self.device).count(),
            4,
        )

    def test_pb_upload_is_idempotent_for_exact_retry(self):
        from business_support.models import DeviceMetricReceipt

        body = _iwown_five_metric_body(self.device_id)
        upload_url = reverse("iwown_health_data_upload")

        first_response = self.client.post(
            upload_url,
            data=body,
            content_type="application/x-www-form-urlencoded",
        )
        second_response = self.client.post(
            upload_url,
            data=body,
            content_type="application/x-www-form-urlencoded",
        )

        self.assertEqual(first_response.content, b"\x00")
        self.assertEqual(second_response.content, b"\x00")
        self.assertEqual(
            HealthMetric.objects.filter(patient=self.patient).count(),
            5,
        )
        self.assertEqual(
            DeviceMetricReceipt.objects.filter(device=self.device).count(),
            4,
        )

    def test_pb_upload_unknown_device_log_does_not_expose_imei(self):
        body = _iwown_five_metric_body(self.device_id)
        self.device.delete()

        with self.assertLogs(
            "health_data.services.device_metric_ingestion",
            level="WARNING",
        ) as captured:
            response = self.client.post(
                reverse("iwown_health_data_upload"),
                data=body,
                content_type="application/x-www-form-urlencoded",
            )

        self.assertEqual(response.content, b"\x00")
        log_text = "\n".join(captured.output)
        self.assertNotIn(self.device_id, log_text)
        self.assertIn(hashlib.sha256(self.device_id.encode()).hexdigest(), log_text)
        self.assertIn("2223", log_text)


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

        received_at = timezone.make_aware(datetime(2025, 12, 10, 9, 20))
        result = DeviceMetricIngestionService.ingest_readings(
            [reading],
            received_at=received_at,
        )

        self.assertEqual(result.created_count, 1)
        self.assertEqual(result.skipped_count, 0)
        metric = HealthMetric.objects.get(patient=self.patient, metric_type=MetricType.BLOOD_OXYGEN)
        self.assertEqual(metric.source, MetricSource.DEVICE)
        self.assertEqual(metric.value_main, Decimal("96"))
        self.assertEqual(metric.measured_at, self.measured_at)
        self.device.refresh_from_db()
        self.assertEqual(self.device.last_active_at, received_at)

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

    def test_ingest_does_not_regress_device_last_active_at(self):
        from business_support.services.device_integrations.base import DeviceMetricReading
        from health_data.services.device_metric_ingestion import DeviceMetricIngestionService

        latest_activity = timezone.make_aware(datetime(2025, 12, 10, 10, 0))
        older_receipt = timezone.make_aware(datetime(2025, 12, 10, 9, 30))
        self.device.last_active_at = latest_activity
        self.device.save(update_fields=["last_active_at"])
        reading = DeviceMetricReading(
            provider_code="HRT",
            device_no=self.device.imei,
            measured_at=self.measured_at,
            metric_type=MetricType.HEART_RATE,
            value_main=Decimal("72"),
            external_event_id="hrt:older-receipt",
        )

        DeviceMetricIngestionService.ingest_readings(
            [reading],
            received_at=older_receipt,
        )

        self.device.refresh_from_db()
        self.assertEqual(self.device.last_active_at, latest_activity)

    def test_ingest_readings_rolls_back_whole_batch_when_later_reading_fails(self):
        from business_support.models import DeviceMetricReceipt
        from business_support.services.device_integrations.base import DeviceMetricReading
        from health_data.services.device_metric_ingestion import DeviceMetricIngestionService
        from health_data.services.health_metric import HealthMetricService

        readings = [
            DeviceMetricReading(
                provider_code="HRT",
                device_no=self.device.imei,
                measured_at=self.measured_at,
                metric_type=MetricType.HEART_RATE,
                value_main=Decimal("72"),
                external_event_id="hrt:batch-failure:heart-rate",
            ),
            DeviceMetricReading(
                provider_code="HRT",
                device_no=self.device.imei,
                measured_at=self.measured_at,
                metric_type=MetricType.BLOOD_OXYGEN,
                value_main=Decimal("96"),
                external_event_id="hrt:batch-failure:blood-oxygen",
            ),
        ]
        original_save = HealthMetricService.save_device_metric
        call_count = 0

        def fail_on_second_reading(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("simulated second metric failure")
            return original_save(**kwargs)

        with patch.object(
            HealthMetricService,
            "save_device_metric",
            side_effect=fail_on_second_reading,
        ):
            with self.assertRaisesMessage(
                RuntimeError,
                "simulated second metric failure",
            ):
                DeviceMetricIngestionService.ingest_readings(readings)

        self.assertFalse(HealthMetric.objects.filter(patient=self.patient).exists())
        self.assertFalse(DeviceMetricReceipt.objects.filter(device=self.device).exists())
        self.device.refresh_from_db()
        self.assertIsNone(self.device.last_active_at)

    def test_ingest_does_not_dedupe_identical_values_from_different_devices(self):
        from business_support.models import DeviceProvider
        from business_support.services.device_integrations.base import DeviceMetricReading
        from health_data.services.device_metric_ingestion import DeviceMetricIngestionService

        iwown_device = Device.objects.create(
            provider=DeviceProvider.objects.get(code="IWOWN"),
            sn="SN-IWOWN-INGEST-002",
            imei="860132060872224",
            current_patient=self.patient,
        )
        readings = [
            DeviceMetricReading(
                provider_code="HRT",
                device_no=self.device.imei,
                measured_at=self.measured_at,
                metric_type=MetricType.HEART_RATE,
                value_main=Decimal("72"),
                external_event_id="hrt:event-1",
            ),
            DeviceMetricReading(
                provider_code="IWOWN",
                device_no=iwown_device.imei,
                measured_at=self.measured_at,
                metric_type=MetricType.HEART_RATE,
                value_main=Decimal("72"),
                external_event_id="0x80:0:1",
            ),
        ]

        first_result = DeviceMetricIngestionService.ingest_readings([readings[0]])
        second_result = DeviceMetricIngestionService.ingest_readings([readings[1]])

        self.assertEqual(first_result.created_count, 1)
        self.assertEqual(second_result.created_count, 1)
        self.assertEqual(
            HealthMetric.objects.filter(
                patient=self.patient,
                metric_type=MetricType.HEART_RATE,
            ).count(),
            2,
        )

    def test_ingest_device_lock_query_does_not_join_provider_table(self):
        from business_support.services.device_integrations.base import DeviceMetricReading
        from health_data.services.device_metric_ingestion import DeviceMetricIngestionService

        reading = DeviceMetricReading(
            provider_code="HRT",
            device_no=self.device.imei,
            measured_at=self.measured_at,
            metric_type=MetricType.HEART_RATE,
            value_main=Decimal("72"),
            external_event_id="hrt:no-provider-join",
        )

        with CaptureQueriesContext(connection) as captured:
            DeviceMetricIngestionService.ingest_readings([reading])

        lock_queries = [
            query["sql"]
            for query in captured.captured_queries
            if "FOR UPDATE" in query["sql"].upper()
            and "business_support_device" in query["sql"]
        ]
        self.assertTrue(lock_queries)
        self.assertTrue(
            all(" JOIN " not in query.upper() for query in lock_queries),
            lock_queries,
        )


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
