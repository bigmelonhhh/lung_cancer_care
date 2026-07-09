from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any


class DeviceCallbackParseError(ValueError):
    """Raised when a provider callback body cannot be parsed."""


@dataclass(frozen=True)
class DeviceMetricReading:
    """
    Provider-neutral metric reading produced by a device integration adapter.

    Business services should depend on this shape instead of provider-specific
    payloads such as HRT's ``BPG`` or ``watchData`` structures.
    """

    provider_code: str
    device_no: str
    measured_at: datetime
    metric_type: str
    value_main: Decimal
    value_sub: Decimal | None = None
    raw_payload: dict[str, Any] | None = None
    external_event_id: str | None = None


@dataclass(frozen=True)
class DeviceCallbackPayload:
    """Normalized callback payload returned by a provider adapter."""

    provider_code: str
    raw_event_type: int | str | None
    readings: list[DeviceMetricReading]
    raw_payload: dict[str, Any]
