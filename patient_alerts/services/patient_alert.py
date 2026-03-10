from __future__ import annotations

from datetime import datetime
from typing import Any

from django.core.exceptions import ValidationError
from django.utils import timezone

from patient_alerts.models import AlertEventType, AlertLevel, AlertStatus, PatientAlert
from users.models import CustomUser, PatientProfile


_STATUS_CODE_BY_VALUE = {
    AlertStatus.PENDING: "pending",
    AlertStatus.ESCALATED: "escalate",
    AlertStatus.COMPLETED: "completed",
}


class PatientAlertService:
    """
    【功能说明】
    - 负责患者报警记录的创建与状态更新。
    - Service 层统一校验输入参数并返回业务对象。
    """

    @staticmethod
    def _get_user_display_name(user: CustomUser | None) -> str:
        if not user:
            return ""

        doctor_profile = getattr(user, "doctor_profile", None)
        assistant_profile = getattr(user, "assistant_profile", None)

        if doctor_profile and getattr(doctor_profile, "name", ""):
            return doctor_profile.name
        if assistant_profile and getattr(assistant_profile, "name", ""):
            return assistant_profile.name
        if getattr(user, "wx_nickname", ""):
            return user.wx_nickname
        if getattr(user, "name", ""):
            return user.name
        if hasattr(user, "get_full_name") and user.get_full_name():
            return user.get_full_name()
        return getattr(user, "username", "") or getattr(user, "phone", "")

    @staticmethod
    def _normalize_handle_meta(handle_meta: Any) -> dict[str, Any]:
        if not isinstance(handle_meta, dict):
            return {"latest": {}, "history": []}

        latest = handle_meta.get("latest")
        history = handle_meta.get("history")
        return {
            "latest": latest if isinstance(latest, dict) else {},
            "history": history if isinstance(history, list) else [],
        }

    @staticmethod
    def _serialize_handled_at(value: datetime | None) -> str:
        if value is None:
            return ""
        if timezone.is_naive(value):
            value = timezone.make_aware(value, timezone.get_current_timezone())
        return timezone.localtime(value).isoformat()

    @staticmethod
    def _build_handle_snapshot(alert: PatientAlert) -> dict[str, Any]:
        handler = getattr(alert, "handler", None)
        return {
            "status": alert.status,
            "status_code": _STATUS_CODE_BY_VALUE.get(alert.status, ""),
            "status_display": alert.get_status_display(),
            "handle_content": alert.handle_content or "",
            "handled_at": PatientAlertService._serialize_handled_at(alert.handle_time),
            "handler_id": alert.handler_id,
            "handler_name": PatientAlertService._get_user_display_name(handler),
        }

    @staticmethod
    def create_alert(
        patient_id: int,
        *,
        event_type: str,
        event_level: int,
        event_title: str,
        event_content: str = "",
        event_time: datetime | None = None,
        doctor_id: int | None = None,
        status: int = AlertStatus.PENDING,
        source_type: str = "",
        source_id: int | None = None,
        source_payload: dict[str, Any] | None = None,
    ) -> PatientAlert:
        """
        创建一条患者报警记录。

        【功能说明】
        - 校验参数有效性并写入 PatientAlert；
        - 未指定 doctor_id 时自动使用患者档案的归属医生。

        【使用方法】
        - PatientAlertService.create_alert(...)

        【参数说明】
        - patient_id: int，患者 ID。
        - event_type: str，事件类型（AlertEventType）。
        - event_level: int，事件等级（AlertLevel）。
        - event_title: str，事件标题。
        - event_content: str，事件内容。
        - event_time: datetime | None，事件时间；不传则取当前时间。
        - doctor_id: int | None，指定处理医生；为空则使用患者主治医生。
        - status: int，处理状态（AlertStatus）。
        - source_type: str，来源类型标识。
        - source_id: int | None，来源记录 ID。
        - source_payload: dict | None，来源快照。

        【返回值说明】
        - PatientAlert 实例。

        【异常说明】
        - ValidationError: 参数无效或患者不存在。
        """
        if not event_title:
            raise ValidationError("event_title is required.")
        if event_type not in AlertEventType.values:
            raise ValidationError("event_type is invalid.")
        if event_level not in AlertLevel.values:
            raise ValidationError("event_level is invalid.")
        if status not in AlertStatus.values:
            raise ValidationError("status is invalid.")

        try:
            patient = PatientProfile.objects.select_related("doctor").get(id=patient_id)
        except PatientProfile.DoesNotExist as exc:
            raise ValidationError("patient_id is invalid.") from exc

        if event_time is None:
            event_time = timezone.now()

        alert = PatientAlert.objects.create(
            patient_id=patient.id,
            doctor_id=doctor_id or patient.doctor_id,
            event_type=event_type,
            event_level=event_level,
            event_title=event_title,
            event_content=event_content,
            event_time=event_time,
            status=status,
            source_type=source_type,
            source_id=source_id,
            source_payload=source_payload or {},
        )
        return alert

    @staticmethod
    def create_or_update_alert(
        patient_id: int,
        *,
        event_type: str,
        event_level: int,
        event_title: str,
        event_content: str = "",
        event_time: datetime | None = None,
        doctor_id: int | None = None,
        status: int = AlertStatus.PENDING,
        source_type: str = "",
        source_id: int | None = None,
        source_payload: dict[str, Any] | None = None,
        dedup_filters: dict[str, Any] | None = None,
    ) -> PatientAlert:
        """
        创建或升级患者报警记录。

        【功能说明】
        - 若存在待处理的同类事件，则升级等级并更新内容；
        - 否则创建新报警记录。

        【使用方法】
        - PatientAlertService.create_or_update_alert(...)

        【参数说明】
        - dedup_filters: dict | None，去重过滤条件，例如 {"event_title": "血氧异常"}。

        【返回值说明】
        - PatientAlert 实例。

        【异常说明】
        - ValidationError: 参数无效或患者不存在。
        """
        if not event_title:
            raise ValidationError("event_title is required.")
        if event_type not in AlertEventType.values:
            raise ValidationError("event_type is invalid.")
        if event_level not in AlertLevel.values:
            raise ValidationError("event_level is invalid.")
        if status not in AlertStatus.values:
            raise ValidationError("status is invalid.")

        try:
            patient = PatientProfile.objects.select_related("doctor").get(id=patient_id)
        except PatientProfile.DoesNotExist as exc:
            raise ValidationError("patient_id is invalid.") from exc

        if event_time is None:
            event_time = timezone.now()

        qs = PatientAlert.objects.filter(
            patient_id=patient.id,
            event_type=event_type,
            is_active=True,
            status__in=[AlertStatus.PENDING, AlertStatus.ESCALATED],
        )
        if dedup_filters:
            qs = qs.filter(**dedup_filters)

        existing = qs.order_by("-event_time", "-id").first()
        if not existing:
            return PatientAlert.objects.create(
                patient_id=patient.id,
                doctor_id=doctor_id or patient.doctor_id,
                event_type=event_type,
                event_level=event_level,
                event_title=event_title,
                event_content=event_content,
                event_time=event_time,
                status=status,
                source_type=source_type,
                source_id=source_id,
                source_payload=source_payload or {},
            )

        updated_fields = []
        new_level = max(existing.event_level, event_level)
        if new_level != existing.event_level:
            existing.event_level = new_level
            updated_fields.append("event_level")
        if event_time and event_time > existing.event_time:
            existing.event_time = event_time
            updated_fields.append("event_time")
        if existing.event_title != event_title:
            existing.event_title = event_title
            updated_fields.append("event_title")
        if existing.event_content != event_content:
            existing.event_content = event_content
            updated_fields.append("event_content")
        if existing.source_type != source_type:
            existing.source_type = source_type
            updated_fields.append("source_type")
        if existing.source_id != source_id:
            existing.source_id = source_id
            updated_fields.append("source_id")
        if source_payload is not None and existing.source_payload != source_payload:
            existing.source_payload = source_payload
            updated_fields.append("source_payload")

        if updated_fields:
            existing.save(update_fields=updated_fields)
        return existing

    @staticmethod
    def update_status(
        alert_id: int,
        *,
        status: int,
        handler_id: int | None = None,
        handle_content: str | None = None,
        handled_at: datetime | None = None,
    ) -> PatientAlert:
        """
        更新报警处理状态与处理信息。

        【功能说明】
        - 更新状态、处理人、处理内容和处理时间；
        - 未传 handled_at 时默认使用当前时间。

        【使用方法】
        - PatientAlertService.update_status(...)

        【参数说明】
        - alert_id: int，报警记录 ID。
        - status: int，处理状态（AlertStatus）。
        - handler_id: int | None，处理人 ID。
        - handle_content: str | None，处理说明。
        - handled_at: datetime | None，处理时间。

        【返回值说明】
        - PatientAlert 实例。

        【异常说明】
        - ValidationError: 参数无效或记录不存在。
        """
        if status not in AlertStatus.values:
            raise ValidationError("status is invalid.")

        try:
            alert = PatientAlert.objects.get(id=alert_id)
        except PatientAlert.DoesNotExist as exc:
            raise ValidationError("alert_id is invalid.") from exc

        alert.status = status
        fields = ["status"]

        if handler_id is not None:
            alert.handler_id = handler_id
            fields.append("handler")

        if handle_content is not None:
            alert.handle_content = handle_content
            fields.append("handle_content")

        if handled_at is None:
            handled_at = timezone.now()
        alert.handle_time = handled_at
        fields.append("handle_time")

        alert.handle_meta = PatientAlertService._normalize_handle_meta(alert.handle_meta)
        snapshot = PatientAlertService._build_handle_snapshot(alert)
        alert.handle_meta["latest"] = snapshot
        alert.handle_meta["history"].append(snapshot)
        fields.append("handle_meta")

        alert.save(update_fields=fields)
        return alert

    @staticmethod
    def get_detail(alert_id: int) -> PatientAlert:
        """
        查询单条患者待办详情。

        【功能说明】
        - 返回指定报警记录的详情，用于详情页展示。

        【使用方法】
        - PatientAlertService.get_detail(alert_id)

        【参数说明】
        - alert_id: int，报警记录 ID。

        【返回值说明】
        - PatientAlert 实例（含关联 patient/doctor/handler）。

        【异常说明】
        - ValidationError: 记录不存在或参数无效。
        """
        if not alert_id:
            raise ValidationError("alert_id is invalid.")

        try:
            return PatientAlert.objects.select_related(
                "patient", "doctor", "handler"
            ).get(id=alert_id)
        except PatientAlert.DoesNotExist as exc:
            raise ValidationError("alert_id is invalid.") from exc
