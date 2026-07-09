"""
Device service layer: binding/unbinding and smartwatch integration.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from django.db import transaction
from django.utils import timezone

from business_support.models import Device
from users.models import PatientProfile


logger = logging.getLogger(__name__)


class DeviceServiceError(Exception):
    """Base class for device service errors."""


class DeviceNotFoundError(DeviceServiceError):
    pass


class PatientNotFoundError(DeviceServiceError):
    pass


class DeviceInactiveError(DeviceServiceError):
    pass


class DeviceOccupiedError(DeviceServiceError):
    pass


class DeviceTypeConflictError(DeviceServiceError):
    pass


class DeviceNotBoundError(DeviceServiceError):
    pass


class DeviceActionStatus(str, Enum):
    BOUND = "bound"
    ALREADY_BOUND = "already_bound"
    UNBOUND = "unbound"


@dataclass(frozen=True)
class DeviceActionResult:
    device: Device
    status: DeviceActionStatus


def bind_device(imei: str, patient_id: int) -> DeviceActionResult:
    """
    Bind the device identified by IMEI to the patient.

    Rules:
    - Device must exist and be active.
    - Device cannot already belong to another patient.
    - The patient cannot have another device of the same type.
    - If the device is already bound to the same patient, it is treated as a no-op,
      but last_active_at is still updated and status is `ALREADY_BOUND`.
    """

    normalized_imei = _normalize_imei(imei)
    now = timezone.now()
    device_id = None

    try:
        with transaction.atomic():
            device = _lock_device_by_imei(normalized_imei)
            device_id = device.pk

            if not device.is_active:
                raise DeviceInactiveError("设备已停用，无法绑定。")

            patient = _lock_patient(patient_id)
            if not patient:
                raise PatientNotFoundError("患者不存在或已被删除。")

            if device.current_patient_id and device.current_patient_id != patient_id:
                raise DeviceOccupiedError("该设备已绑定其他患者，请先解绑。")

            conflict_exists = (
                Device.objects.select_for_update()
                .filter(current_patient_id=patient_id, device_type=device.device_type)
                .exclude(pk=device.pk)
                .exists()
            )
            if conflict_exists:
                raise DeviceTypeConflictError("该患者已绑定同类型设备，请先解绑。")

            if device.current_patient_id == patient_id:
                device.last_active_at = now
                device.save(update_fields=["last_active_at"])
                return DeviceActionResult(device=device, status=DeviceActionStatus.ALREADY_BOUND)

            device.current_patient = patient
            device.bind_at = now
            device.last_active_at = now
            device.save(update_fields=["current_patient", "bind_at", "last_active_at"])
            return DeviceActionResult(device=device, status=DeviceActionStatus.BOUND)
    except DeviceServiceError:
        if device_id:
            _touch_last_active(device_id, now)
        raise


def unbind_device(imei: str, patient_id: int) -> DeviceActionResult:
    """
    Unbind the device identified by IMEI from the patient.
    """

    normalized_imei = _normalize_imei(imei)
    now = timezone.now()
    device_id = None

    try:
        with transaction.atomic():
            device = _lock_device_by_imei(normalized_imei)
            device_id = device.pk

            patient = _lock_patient(patient_id)
            if not patient:
                raise PatientNotFoundError("患者不存在或已被删除。")

            if device.current_patient_id != patient_id:
                raise DeviceNotBoundError("该设备未绑定指定患者，无需解绑。")

            device.current_patient = None
            device.bind_at = None
            device.last_active_at = now
            device.save(update_fields=["current_patient", "bind_at", "last_active_at"])
            return DeviceActionResult(device=device, status=DeviceActionStatus.UNBOUND)
    except DeviceServiceError:
        if device_id:
            _touch_last_active(device_id, now)
        raise


def _normalize_imei(imei: str) -> str:
    if not imei:
        raise DeviceServiceError("IMEI 不能为空。")
    value = imei.strip()
    if not value:
        raise DeviceServiceError("IMEI 不能为空。")
    return value


def _lock_device_by_imei(imei: str) -> Device:
    try:
        return Device.objects.select_for_update().get(imei=imei)
    except Device.DoesNotExist as exc:
        raise DeviceNotFoundError("设备不存在，请确认 IMEI 是否正确。") from exc


def _lock_patient(patient_id: int) -> PatientProfile | None:
    if not patient_id:
        return None
    return PatientProfile.objects.select_for_update().filter(pk=patient_id).first()


def _touch_last_active(device_id: int, when):
    Device.objects.filter(pk=device_id).update(last_active_at=when)
