from __future__ import annotations

import logging
from dataclasses import dataclass

from django.db import transaction

from business_support.models import Device
from business_support.services.device_integrations.base import DeviceMetricReading
from health_data.services.health_metric import HealthMetricService


logger = logging.getLogger(__name__)


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
        cls, readings: list[DeviceMetricReading] | tuple[DeviceMetricReading, ...]
    ) -> DeviceMetricIngestionResult:
        created_count = 0
        skipped_count = 0

        for reading in readings:
            metric = cls.ingest_reading(reading)
            if metric is None:
                skipped_count += 1
            else:
                created_count += 1

        return DeviceMetricIngestionResult(
            created_count=created_count,
            skipped_count=skipped_count,
        )

    @classmethod
    def ingest_reading(cls, reading: DeviceMetricReading):
        device = cls._find_device(reading)
        if not device:
            logger.warning(
                "未找到匹配设备 provider=%s device_no=%s，跳过。",
                reading.provider_code,
                reading.device_no,
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

        with transaction.atomic():
            Device.objects.filter(pk=device.pk).update(last_active_at=reading.measured_at)
            return HealthMetricService.save_device_metric(
                patient_id=device.current_patient_id,
                metric_type=reading.metric_type,
                measured_at=reading.measured_at,
                value_main=reading.value_main,
                value_sub=reading.value_sub,
            )

    @classmethod
    def _find_device(cls, reading: DeviceMetricReading) -> Device | None:
        provider_code = (reading.provider_code or "").strip().upper()
        device_no = (reading.device_no or "").strip()
        if not device_no:
            return None

        base_filter = {"provider__code": provider_code}
        device = cls._query_device(device_no, **base_filter)
        if device:
            return device

        return None

    @staticmethod
    def _query_device(device_no: str, **filters) -> Device | None:
        return (
            Device.objects.select_related("provider", "current_patient")
            .filter(imei=device_no, **filters)
            .first()
        ) or (
            Device.objects.select_related("provider", "current_patient")
            .filter(sn=device_no, **filters)
            .first()
        )
