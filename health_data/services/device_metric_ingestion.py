from __future__ import annotations

import logging
import hashlib
from dataclasses import dataclass
from datetime import datetime

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from business_support.models import Device, DeviceMetricReceipt, DeviceProvider
from business_support.services.device_integrations.base import DeviceMetricReading
from health_data.models import MetricType
from health_data.services.health_metric import HealthMetricService


logger = logging.getLogger(__name__)


def _device_log_fields(device_no: str) -> dict[str, str]:
    normalized = (device_no or "").strip()
    return {
        "device_id_hash": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        "device_id_suffix": normalized[-4:],
    }


@dataclass(frozen=True)
class DeviceMetricIngestionResult:
    created_count: int
    skipped_count: int


class DeviceMetricIngestionService:
    """
    Ingest provider-neutral device readings into business health metrics.

    Provider adapters translate external payloads into ``DeviceMetricReading``.
    This service owns platform rules: device lookup, active/bound checks, device
    liveness update, and delegation to health metric business logic.
    """

    @classmethod
    def ingest_readings(
        cls,
        readings: list[DeviceMetricReading] | tuple[DeviceMetricReading, ...],
        *,
        received_at: datetime | None = None,
    ) -> DeviceMetricIngestionResult:
        """Persist one callback batch atomically and suppress exact retries."""
        activity_at = received_at or timezone.now()
        with transaction.atomic():
            created_count = 0
            skipped_count = 0

            for reading in readings:
                metric = cls.ingest_reading(reading, received_at=activity_at)
                if metric is None:
                    skipped_count += 1
                else:
                    created_count += 1

            return DeviceMetricIngestionResult(
                created_count=created_count,
                skipped_count=skipped_count,
            )

    @classmethod
    def ingest_reading(
        cls,
        reading: DeviceMetricReading,
        *,
        received_at: datetime | None = None,
    ):
        with transaction.atomic():
            device = cls._find_device(reading, for_update=True)
            if not device:
                logger.warning(
                    {
                        "event": "device_metric_device_not_found",
                        "provider": reading.provider_code,
                        **_device_log_fields(reading.device_no),
                    }
                )
                return None
            if not device.is_active:
                logger.info("设备 %s 已停用，跳过数据。", device.pk)
                return None
            if device.provider and not device.provider.is_active:
                logger.info("设备厂商 %s 已停用，跳过数据。", device.provider.code)
                return None
            if not device.current_patient_id:
                logger.info("设备 %s 未绑定患者，跳过数据。", device.pk)
                return None

            activity_at = received_at or timezone.now()
            Device.objects.filter(pk=device.pk).filter(
                Q(last_active_at__isnull=True) | Q(last_active_at__lt=activity_at)
            ).update(last_active_at=activity_at)
            if cls._is_exact_retry(device, reading):
                logger.info(
                    {
                        "event": "device_metric_duplicate_skipped",
                        "provider": reading.provider_code,
                        "device_id": device.pk,
                        "metric_type": reading.metric_type,
                        "measured_at": reading.measured_at,
                    }
                )
                return None
            metric = HealthMetricService.save_device_metric(
                patient_id=device.current_patient_id,
                metric_type=reading.metric_type,
                measured_at=reading.measured_at,
                value_main=reading.value_main,
                value_sub=reading.value_sub,
            )
            if metric is not None:
                cls._record_external_event(device, reading)
            return metric

    @classmethod
    def _find_device(
        cls,
        reading: DeviceMetricReading,
        *,
        for_update: bool = False,
    ) -> Device | None:
        provider_code = (reading.provider_code or "").strip().upper()
        device_no = (reading.device_no or "").strip()
        if not device_no:
            return None

        provider_id = (
            DeviceProvider.objects.filter(code=provider_code)
            .values_list("pk", flat=True)
            .first()
        )
        if provider_id is None:
            return None
        base_filter = {"provider_id": provider_id}
        device = cls._query_device(
            device_no,
            for_update=for_update,
            **base_filter,
        )
        if device:
            return device

        return None

    @staticmethod
    def _query_device(
        device_no: str,
        *,
        for_update: bool = False,
        **filters,
    ) -> Device | None:
        devices = Device.objects.all()
        if for_update:
            devices = devices.select_for_update()
        else:
            devices = devices.select_related("provider", "current_patient")
        return devices.filter(imei=device_no, **filters).first() or devices.filter(
            sn=device_no,
            **filters,
        ).first()

    @staticmethod
    def _is_exact_retry(device: Device, reading: DeviceMetricReading) -> bool:
        """Check a provider event key after locking its device row."""
        if (
            not reading.external_event_id
            or reading.metric_type == MetricType.STEPS
        ):
            return False
        return DeviceMetricReceipt.objects.filter(
            device=device,
            provider_code=(reading.provider_code or "").strip().upper(),
            external_event_id=reading.external_event_id,
            metric_type=reading.metric_type,
        ).exists()

    @staticmethod
    def _record_external_event(
        device: Device,
        reading: DeviceMetricReading,
    ) -> None:
        """Record only successfully persisted non-step provider events."""
        if (
            not reading.external_event_id
            or reading.metric_type == MetricType.STEPS
        ):
            return
        DeviceMetricReceipt.objects.create(
            device=device,
            provider_code=(reading.provider_code or "").strip().upper(),
            external_event_id=reading.external_event_id,
            metric_type=reading.metric_type,
        )
