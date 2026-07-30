from __future__ import annotations

import base64
import hashlib
import json
import logging
import struct
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from django.http import HttpResponse, JsonResponse
from django.utils import timezone

from health_data.models import MetricType

from .base import (
    DeviceCallbackParseError,
    DeviceCallbackPayload,
    DeviceMetricReading,
)


logger = logging.getLogger(__name__)

_MAX_DEVICE_INFO_BODY_BYTES = 64 * 1024
_MAX_POST_LOG_BODY_BYTES = 1024 * 1024
_DEVICE_INFO_LOG_FIELDS = (
    "model",
    "version",
    "watch_event",
)


def log_iwown_post_body(
    *,
    endpoint: str,
    body: bytes,
    content_type: str,
) -> None:
    """Log the exact IWOWN POST body as bounded, reversible Base64."""
    logged_body = body[:_MAX_POST_LOG_BODY_BYTES]
    logger.info(
        {
            "event": "iwown_post_body_received",
            "provider": "IWOWN",
            "endpoint": endpoint,
            "content_type": content_type,
            "body_bytes": len(body),
            "post_body_logged_bytes": len(logged_body),
            "post_body_base64": base64.b64encode(logged_body).decode("ascii"),
            "post_body_truncated": len(logged_body) != len(body),
            "post_body_sha256": hashlib.sha256(body).hexdigest(),
        }
    )


def build_iwown_device_log_fields(device_id: object) -> dict[str, str | None]:
    """Return a stable, non-reversible identifier plus a short support suffix."""
    normalized = str(device_id or "").strip()
    if not normalized:
        return {"device_id_hash": None, "device_id_suffix": None}
    return {
        "device_id_hash": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        "device_id_suffix": normalized[-4:],
    }


class IwownPacketHeaderError(DeviceCallbackParseError):
    """Raised when an IWOWN health packet does not start with ``DT``."""


@dataclass(frozen=True)
class _ProtobufValue:
    wire_type: int
    value: int | bytes


def _decode_varint(data: bytes, position: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while position < len(data) and shift < 70:
        byte = data[position]
        position += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, position
        shift += 7
    raise DeviceCallbackParseError("Invalid IWOWN protobuf varint")


def _parse_protobuf_fields(data: bytes) -> dict[int, list[_ProtobufValue]]:
    """Read the protobuf wire types needed to skip unknown IWOWN fields safely."""
    fields: dict[int, list[_ProtobufValue]] = {}
    position = 0
    while position < len(data):
        key, position = _decode_varint(data, position)
        field_number = key >> 3
        wire_type = key & 0x07
        if field_number == 0:
            raise DeviceCallbackParseError("Invalid IWOWN protobuf field number")

        if wire_type == 0:
            value, position = _decode_varint(data, position)
        elif wire_type == 1:
            end = position + 8
            if end > len(data):
                raise DeviceCallbackParseError("Truncated IWOWN protobuf fixed64")
            value = int.from_bytes(data[position:end], "little")
            position = end
        elif wire_type == 2:
            length, position = _decode_varint(data, position)
            end = position + length
            if end > len(data):
                raise DeviceCallbackParseError("Truncated IWOWN protobuf message")
            value = data[position:end]
            position = end
        elif wire_type == 5:
            end = position + 4
            if end > len(data):
                raise DeviceCallbackParseError("Truncated IWOWN protobuf fixed32")
            value = int.from_bytes(data[position:end], "little")
            position = end
        else:
            raise DeviceCallbackParseError(
                f"Unsupported IWOWN protobuf wire type: {wire_type}"
            )
        fields.setdefault(field_number, []).append(
            _ProtobufValue(wire_type=wire_type, value=value)
        )
    return fields


def _first_field(
    fields: dict[int, list[_ProtobufValue]],
    field_number: int,
    wire_type: int,
) -> int | bytes | None:
    for field in fields.get(field_number, []):
        if field.wire_type == wire_type:
            return field.value
    return None


class IwownHealthDataAdapter:
    """Translate IWOWN binary health uploads into platform metric readings."""

    provider_code = "IWOWN"

    @staticmethod
    def success_response() -> HttpResponse:
        """Acknowledge a valid upload using IWOWN's one-byte protocol."""
        return HttpResponse(b"\x00", content_type="application/octet-stream")

    @staticmethod
    def invalid_data_response(*, status: int = 200) -> HttpResponse:
        """Report a truncated or malformed data packet."""
        return HttpResponse(
            b"\x02",
            content_type="application/octet-stream",
            status=status,
        )

    @staticmethod
    def invalid_header_response() -> HttpResponse:
        """Report a packet whose IWOWN header prefix is invalid."""
        return HttpResponse(b"\x03", content_type="application/octet-stream")

    def parse_body(self, body: bytes) -> DeviceCallbackPayload:
        """Parse the IWOWN envelope and only the health packet options in scope."""
        if len(body) < 23:
            raise DeviceCallbackParseError("IWOWN health body is too short")
        try:
            device_no = body[:15].decode("ascii").strip("\x00 ")
        except UnicodeDecodeError as exc:
            raise DeviceCallbackParseError("Invalid IWOWN device ID") from exc
        if not device_no:
            raise DeviceCallbackParseError("Missing IWOWN device ID")

        readings: list[DeviceMetricReading] = []
        packet_options: list[int] = []
        position = 15
        while position < len(body):
            if len(body) - position < 8:
                raise DeviceCallbackParseError("Truncated IWOWN packet header")
            if body[position : position + 2] != b"DT":
                raise IwownPacketHeaderError("Invalid IWOWN packet prefix")
            payload_length, _crc, option = struct.unpack_from(
                "<HHH", body, position + 2
            )
            payload_start = position + 8
            payload_end = payload_start + payload_length
            if payload_end > len(body):
                raise DeviceCallbackParseError("Truncated IWOWN packet payload")

            payload = body[payload_start:payload_end]
            packet_options.append(option)
            if option == 0x0A:
                readings.extend(self._parse_realtime_steps(device_no, payload))
            elif option == 0x80:
                readings.extend(self._parse_historical_data(device_no, payload))
            position = payload_end

        option_names = [f"0x{option:02X}" for option in packet_options]
        return DeviceCallbackPayload(
            provider_code=self.provider_code,
            raw_event_type=",".join(option_names),
            readings=readings,
            raw_payload={
                "device_no": device_no,
                "packet_options": option_names,
            },
        )

    def log_received(
        self,
        payload: DeviceCallbackPayload,
        *,
        body_bytes: int,
        content_type: str,
        created_count: int,
        skipped_count: int,
    ) -> None:
        """Log a readable summary of the decoded health upload."""
        parsed_readings = [
            {
                "device_no": reading.device_no,
                "measured_at": reading.measured_at.isoformat(),
                "metric_type": reading.metric_type,
                "value_main": str(reading.value_main),
                "value_sub": (
                    str(reading.value_sub)
                    if reading.value_sub is not None
                    else None
                ),
                "raw_payload": reading.raw_payload,
                "external_event_id": reading.external_event_id,
            }
            for reading in payload.readings
        ]
        logger.info(
            {
                "event": "iwown_health_data_received",
                "provider": self.provider_code,
                **build_iwown_device_log_fields(payload.raw_payload.get("device_no")),
                "body_bytes": body_bytes,
                "content_type": content_type,
                "packet_options": payload.raw_payload.get("packet_options", []),
                "reading_count": len(payload.readings),
                "created_count": created_count,
                "skipped_count": skipped_count,
                "parsed_readings": parsed_readings,
            }
        )

    def log_invalid(
        self,
        *,
        body_bytes: int,
        content_type: str,
        error: DeviceCallbackParseError,
    ) -> None:
        """Log invalid health-packet metadata without exposing its raw body."""
        logger.warning(
            {
                "event": "iwown_health_data_invalid",
                "provider": self.provider_code,
                "body_bytes": body_bytes,
                "content_type": content_type,
                "error": str(error),
            }
        )

    def _parse_realtime_steps(
        self, device_no: str, payload: bytes
    ) -> list[DeviceMetricReading]:
        report = _parse_protobuf_fields(payload)
        health_payload = _first_field(report, 5, 2)
        if not isinstance(health_payload, bytes):
            return []
        health = _parse_protobuf_fields(health_payload)
        steps = _first_field(health, 1, 5)
        if not isinstance(steps, int):
            return []

        measured_at = self._parse_datetime(_first_field(report, 6, 2))
        external_event_id = f"0x0A:{hashlib.sha256(payload).hexdigest()}"
        return [
            DeviceMetricReading(
                provider_code=self.provider_code,
                device_no=device_no,
                measured_at=measured_at,
                metric_type=MetricType.STEPS,
                value_main=Decimal(steps),
                raw_payload={"option": "0x0A", "steps": steps},
                external_event_id=external_event_id,
            )
        ]

    def _parse_historical_data(
        self, device_no: str, payload: bytes
    ) -> list[DeviceMetricReading]:
        notification = _parse_protobuf_fields(payload)
        data_type = _first_field(notification, 1, 0)
        history_payload = _first_field(notification, 4, 2)
        if not isinstance(history_payload, bytes):
            return []

        history_data = _parse_protobuf_fields(history_payload)
        sequence = _first_field(history_data, 1, 5)
        if not isinstance(sequence, int):
            raise DeviceCallbackParseError("Missing IWOWN history sequence")
        external_event_id = (
            f"0x80:{data_type}:{sequence}:{hashlib.sha256(payload).hexdigest()}"
        )
        if data_type == 0:
            health_payload = _first_field(history_data, 3, 2)
            if isinstance(health_payload, bytes):
                return self._parse_historical_health(
                    device_no,
                    health_payload,
                    sequence=sequence,
                    external_event_id=external_event_id,
                )
        elif data_type == 14:
            third_party_payload = _first_field(history_data, 16, 2)
            if isinstance(third_party_payload, bytes):
                return self._parse_third_party_data(
                    device_no,
                    third_party_payload,
                    sequence=sequence,
                    external_event_id=external_event_id,
                )
        return []

    def _parse_historical_health(
        self,
        device_no: str,
        payload: bytes,
        *,
        sequence: int,
        external_event_id: str,
    ) -> list[DeviceMetricReading]:
        health = _parse_protobuf_fields(payload)
        measured_at = self._parse_datetime(
            _first_field(health, 1, 2),
            required=True,
        )
        readings: list[DeviceMetricReading] = []

        heart_rate_payload = _first_field(health, 4, 2)
        if isinstance(heart_rate_payload, bytes):
            heart_rate = _parse_protobuf_fields(heart_rate_payload)
            average_bpm = _first_field(heart_rate, 3, 5)
            if isinstance(average_bpm, int):
                readings.append(
                    self._build_reading(
                        device_no,
                        measured_at,
                        MetricType.HEART_RATE,
                        average_bpm,
                        sequence=sequence,
                        external_event_id=external_event_id,
                        raw_values={"avg_bpm": average_bpm},
                    )
                )

        blood_pressure_payload = _first_field(health, 6, 2)
        if isinstance(blood_pressure_payload, bytes):
            blood_pressure = _parse_protobuf_fields(blood_pressure_payload)
            systolic = _first_field(blood_pressure, 1, 5)
            diastolic = _first_field(blood_pressure, 2, 5)
            if isinstance(systolic, int) and isinstance(diastolic, int):
                readings.append(
                    self._build_reading(
                        device_no,
                        measured_at,
                        MetricType.BLOOD_PRESSURE,
                        systolic,
                        value_sub=diastolic,
                        sequence=sequence,
                        external_event_id=external_event_id,
                        raw_values={"sbp": systolic, "dbp": diastolic},
                    )
                )

        blood_oxygen_payload = _first_field(health, 12, 2)
        if isinstance(blood_oxygen_payload, bytes):
            blood_oxygen = _parse_protobuf_fields(blood_oxygen_payload)
            average_oxygen = _first_field(blood_oxygen, 3, 5)
            if isinstance(average_oxygen, int):
                readings.append(
                    self._build_reading(
                        device_no,
                        measured_at,
                        MetricType.BLOOD_OXYGEN,
                        average_oxygen,
                        sequence=sequence,
                        external_event_id=external_event_id,
                        raw_values={"avg_oxy": average_oxygen},
                    )
                )

        blood_sugar_payload = _first_field(health, 18, 2)
        if isinstance(blood_sugar_payload, bytes):
            blood_sugar = _parse_protobuf_fields(blood_sugar_payload)
            sugar = _first_field(blood_sugar, 1, 5)
            glucose = self._normalize_tenths_mmol_per_l(sugar)
            if glucose is not None:
                readings.append(
                    self._build_reading(
                        device_no,
                        measured_at,
                        MetricType.BLOOD_GLUCOSE,
                        glucose,
                        sequence=sequence,
                        external_event_id=external_event_id,
                        raw_values={"blood_sugar": sugar},
                    )
                )

        uric_acid_payload = _first_field(health, 21, 2)
        if isinstance(uric_acid_payload, bytes):
            uric_acid = _parse_protobuf_fields(uric_acid_payload)
            value = _first_field(uric_acid, 1, 5)
            if isinstance(value, int):
                readings.append(
                    self._build_reading(
                        device_no,
                        measured_at,
                        MetricType.URIC_ACID,
                        value,
                        sequence=sequence,
                        external_event_id=external_event_id,
                        raw_values={"uric_acid": value},
                    )
                )

        return readings

    def _parse_third_party_data(
        self,
        device_no: str,
        payload: bytes,
        *,
        sequence: int,
        external_event_id: str,
    ) -> list[DeviceMetricReading]:
        third_party = _parse_protobuf_fields(payload)
        health_payload = _first_field(third_party, 1, 2)
        if not isinstance(health_payload, bytes):
            return []
        health = _parse_protobuf_fields(health_payload)
        readings: list[DeviceMetricReading] = []
        heart_rate_added = False

        blood_pressure_payload = _first_field(health, 5, 2)
        if isinstance(blood_pressure_payload, bytes):
            blood_pressure = _parse_protobuf_fields(blood_pressure_payload)
            measured_at = self._parse_datetime(
                _first_field(blood_pressure, 5, 2),
                required=True,
            )
            systolic = _first_field(blood_pressure, 1, 5)
            diastolic = _first_field(blood_pressure, 2, 5)
            heart_rate = _first_field(blood_pressure, 3, 5)
            if isinstance(systolic, int) and isinstance(diastolic, int):
                readings.append(
                    self._build_reading(
                        device_no,
                        measured_at,
                        MetricType.BLOOD_PRESSURE,
                        systolic,
                        value_sub=diastolic,
                        sequence=sequence,
                        external_event_id=external_event_id,
                        raw_values={"sbp": systolic, "dbp": diastolic},
                    )
                )
            if isinstance(heart_rate, int):
                readings.append(
                    self._build_reading(
                        device_no,
                        measured_at,
                        MetricType.HEART_RATE,
                        heart_rate,
                        sequence=sequence,
                        external_event_id=external_event_id,
                        raw_values={"heart_rate": heart_rate},
                    )
                )
                heart_rate_added = True

        scale_payload = _first_field(health, 6, 2)
        if isinstance(scale_payload, bytes):
            scale = _parse_protobuf_fields(scale_payload)
            weight = _first_field(scale, 1, 5)
            units = _first_field(scale, 3, 5)
            weight_kg = self._normalize_scale_weight_kg(weight, units)
            if weight_kg is not None:
                readings.append(
                    self._build_reading(
                        device_no,
                        self._parse_datetime(
                            _first_field(scale, 5, 2),
                            required=True,
                        ),
                        MetricType.WEIGHT,
                        weight_kg,
                        sequence=sequence,
                        external_event_id=external_event_id,
                        raw_values={"weight": weight, "units": units},
                    )
                )
            elif isinstance(weight, int):
                logger.warning(
                    {
                        "event": "iwown_weight_skipped",
                        "provider": self.provider_code,
                        **build_iwown_device_log_fields(device_no),
                        "weight": weight,
                        "units": units,
                    }
                )

        blood_oxygen_payload = _first_field(health, 7, 2)
        if isinstance(blood_oxygen_payload, bytes):
            blood_oxygen = _parse_protobuf_fields(blood_oxygen_payload)
            measured_at = self._parse_datetime(
                _first_field(blood_oxygen, 4, 2),
                required=True,
            )
            oxygen = _first_field(blood_oxygen, 2, 5)
            if isinstance(oxygen, int):
                readings.append(
                    self._build_reading(
                        device_no,
                        measured_at,
                        MetricType.BLOOD_OXYGEN,
                        oxygen,
                        sequence=sequence,
                        external_event_id=external_event_id,
                        raw_values={"spo2": oxygen},
                    )
                )
            if not heart_rate_added:
                heart_rate = _first_field(blood_oxygen, 1, 5)
                if isinstance(heart_rate, int):
                    readings.append(
                        self._build_reading(
                            device_no,
                            measured_at,
                            MetricType.HEART_RATE,
                            heart_rate,
                            sequence=sequence,
                            external_event_id=external_event_id,
                            raw_values={"heart_rate": heart_rate},
                        )
                    )

        glucose_payload = _first_field(health, 9, 2)
        if isinstance(glucose_payload, bytes):
            glucose_data = _parse_protobuf_fields(glucose_payload)
            glucose = self._normalize_tenths_mmol_per_l(
                _first_field(glucose_data, 1, 5)
            )
            if glucose is not None:
                readings.append(
                    self._build_reading(
                        device_no,
                        self._parse_datetime(
                            _first_field(glucose_data, 2, 2),
                            required=True,
                        ),
                        MetricType.BLOOD_GLUCOSE,
                        glucose,
                        sequence=sequence,
                        external_event_id=external_event_id,
                        raw_values={
                            "glucose": _first_field(glucose_data, 1, 5),
                        },
                    )
                )

        ketone_payload = _first_field(health, 10, 2)
        if isinstance(ketone_payload, bytes):
            ketone_data = _parse_protobuf_fields(ketone_payload)
            ketone = self._normalize_tenths_mmol_per_l(
                _first_field(ketone_data, 1, 5)
            )
            if ketone is not None:
                readings.append(
                    self._build_reading(
                        device_no,
                        self._parse_datetime(
                            _first_field(ketone_data, 2, 2),
                            required=True,
                        ),
                        MetricType.BLOOD_KETONE,
                        ketone,
                        sequence=sequence,
                        external_event_id=external_event_id,
                        raw_values={
                            "blood_ketones": _first_field(ketone_data, 1, 5),
                        },
                    )
                )

        uric_acid_payload = _first_field(health, 11, 2)
        if isinstance(uric_acid_payload, bytes):
            uric_acid_data = _parse_protobuf_fields(uric_acid_payload)
            uric_acid = _first_field(uric_acid_data, 1, 5)
            if isinstance(uric_acid, int):
                readings.append(
                    self._build_reading(
                        device_no,
                        self._parse_datetime(
                            _first_field(uric_acid_data, 2, 2),
                            required=True,
                        ),
                        MetricType.URIC_ACID,
                        uric_acid,
                        sequence=sequence,
                        external_event_id=external_event_id,
                        raw_values={"uric_acid": uric_acid},
                    )
                )

        return readings

    @staticmethod
    def _normalize_scale_weight_kg(
        weight: object,
        units: object,
    ) -> Decimal | None:
        """Normalize IWOWN scale weight to kg for supported unit encodings."""
        if not isinstance(weight, int) or units != 0:
            return None

        candidates = [Decimal(weight)]
        if weight > 500:
            candidates.append(Decimal(weight) / Decimal("100"))

        for candidate in candidates:
            if Decimal("10") <= candidate <= Decimal("500"):
                return candidate
        return None

    @staticmethod
    def _normalize_tenths_mmol_per_l(value: object) -> Decimal | None:
        """Normalize IWOWN fixed32 mmol/L values encoded with one decimal place."""
        if not isinstance(value, int):
            return None
        return Decimal(value) / Decimal("10")

    def _build_reading(
        self,
        device_no: str,
        measured_at: datetime,
        metric_type: str,
        value_main: int | Decimal,
        *,
        value_sub: int | None = None,
        sequence: int,
        external_event_id: str,
        raw_values: dict[str, int | None],
    ) -> DeviceMetricReading:
        raw_payload: dict[str, Any] = {
            "option": "0x80",
            "metric": raw_values,
        }
        raw_payload["sequence"] = sequence
        return DeviceMetricReading(
            provider_code=self.provider_code,
            device_no=device_no,
            measured_at=measured_at,
            metric_type=metric_type,
            value_main=Decimal(value_main),
            value_sub=Decimal(value_sub) if value_sub is not None else None,
            raw_payload=raw_payload,
            external_event_id=external_event_id,
        )

    @staticmethod
    def _parse_datetime(
        value: int | bytes | None,
        *,
        required: bool = False,
    ) -> datetime:
        if not isinstance(value, bytes):
            if required:
                raise DeviceCallbackParseError("Missing IWOWN measurement time")
            return timezone.now()
        date_time = _parse_protobuf_fields(value)
        rt_time_payload = _first_field(date_time, 1, 2)
        if not isinstance(rt_time_payload, bytes):
            if required:
                raise DeviceCallbackParseError("Invalid IWOWN measurement time")
            return timezone.now()
        rt_time = _parse_protobuf_fields(rt_time_payload)
        seconds = _first_field(rt_time, 1, 5)
        if not isinstance(seconds, int):
            if required:
                raise DeviceCallbackParseError("Invalid IWOWN measurement timestamp")
            return timezone.now()

        wall_clock = datetime.fromtimestamp(seconds, tz=UTC).replace(tzinfo=None)
        return timezone.make_aware(wall_clock, timezone.get_current_timezone())


class IwownDeviceInfoAdapter:
    """Parse and acknowledge IWOWN device-information callbacks."""

    provider_code = "IWOWN"

    @staticmethod
    def parse_body(body: bytes) -> dict[str, Any]:
        """Decode the raw JSON body sent to IWOWN's device-info endpoint."""
        if len(body) > _MAX_DEVICE_INFO_BODY_BYTES:
            raise DeviceCallbackParseError("IWOWN device info body is too large")
        try:
            payload = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise DeviceCallbackParseError("Invalid IWOWN device info JSON") from exc
        if not isinstance(payload, dict):
            raise DeviceCallbackParseError("IWOWN device info must be a JSON object")
        return payload

    def log_received(
        self,
        payload: dict[str, Any],
        *,
        body_bytes: int,
        content_type: str,
    ) -> None:
        """Write a structured callback record for later integration diagnosis."""
        device_info = {
            field: payload[field]
            for field in _DEVICE_INFO_LOG_FIELDS
            if field in payload
        }
        logger.info(
            {
                "event": "iwown_device_info_received",
                "provider": self.provider_code,
                "body_bytes": body_bytes,
                "content_type": content_type,
                **build_iwown_device_log_fields(payload.get("deviceid")),
                "model": payload.get("model"),
                "version": payload.get("version"),
                "watch_event": payload.get("watch_event"),
                "device_info": device_info,
                "payload_keys": sorted(payload),
                "post_payload": payload,
            }
        )

    def log_invalid(
        self,
        body: bytes,
        *,
        content_type: str,
        error: DeviceCallbackParseError,
    ) -> None:
        """Log diagnostic metadata without persisting sensitive raw content."""
        logger.warning(
            {
                "event": "iwown_device_info_invalid",
                "provider": self.provider_code,
                "body_bytes": len(body),
                "content_type": content_type,
                "error": str(error),
                "body_sha256": hashlib.sha256(body).hexdigest(),
            }
        )

    @staticmethod
    def success_response() -> JsonResponse:
        """Return the success contract expected by the IWOWN device."""
        return JsonResponse({"ReturnCode": 0})

    @staticmethod
    def invalid_response(*, status: int = 200) -> JsonResponse:
        """Return IWOWN's invalid-parameter response contract."""
        return JsonResponse({"ReturnCode": 10002}, status=status)
