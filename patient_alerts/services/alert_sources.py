from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from django.utils import timezone

from health_data.models import HealthMetric, MetricType, QuestionnaireSubmission
from patient_alerts.models import AlertLevel, PatientAlert, PatientAlertSource


_LEVEL_LABELS = {
    AlertLevel.MILD: "1级",
    AlertLevel.MODERATE: "2级",
    AlertLevel.SEVERE: "3级",
}


class PatientAlertSourceService:
    """Create and serialize abnormal source records for patient alerts."""

    @classmethod
    def record_metric_source(
        cls,
        *,
        alert: PatientAlert,
        metric: HealthMetric,
        event_level: int,
        source_payload: dict[str, Any],
    ) -> PatientAlertSource:
        patient = getattr(metric, "patient", None) or alert.patient
        metric_label = cls._get_metric_label(metric.metric_type)
        baseline_display = cls._build_metric_baseline_display(
            patient=patient,
            metric_type=metric.metric_type,
        )
        payload = dict(source_payload or {})
        payload.setdefault("metric_type", metric.metric_type)
        payload.setdefault("metric_id", metric.id)

        return cls.record_source(
            alert=alert,
            patient_id=metric.patient_id,
            source_type="metric",
            source_id=metric.id,
            source_key=f"metric:{metric.id}",
            source_label=metric_label,
            value_display=metric.display_value,
            baseline_display=baseline_display,
            event_level=event_level,
            occurred_at=metric.measured_at,
            source_payload=payload,
        )

    @classmethod
    def record_questionnaire_source(
        cls,
        *,
        alert: PatientAlert,
        submission: QuestionnaireSubmission,
        event_level: int,
        grade_level: int,
        total_score: Decimal,
        source_payload: dict[str, Any],
        value_display: str | None = None,
    ) -> PatientAlertSource:
        score_display = cls._format_decimal(total_score)
        questionnaire_name = submission.questionnaire.name
        payload = dict(source_payload or {})
        payload.setdefault("questionnaire_id", submission.questionnaire_id)
        payload.setdefault("questionnaire_code", submission.questionnaire.code)

        return cls.record_source(
            alert=alert,
            patient_id=submission.patient_id,
            source_type="questionnaire",
            source_id=submission.id,
            source_key=f"questionnaire:{submission.id}",
            source_label=questionnaire_name,
            value_display=(
                value_display
                or f"总分 {score_display}，分级 {grade_level}级"
            ),
            baseline_display="",
            event_level=event_level,
            occurred_at=submission.created_at,
            source_payload=payload,
        )

    @classmethod
    def record_behavior_source(
        cls,
        *,
        alert: PatientAlert,
        patient_id: int,
        source_type: str,
        source_id: int | None,
        title: str,
        content: str,
        event_level: int,
        occurred_at: datetime,
        source_payload: dict[str, Any],
    ) -> PatientAlertSource:
        source_key = cls._build_behavior_source_key(
            patient_id=patient_id,
            source_type=source_type,
            source_id=source_id,
            payload=source_payload,
        )
        return cls.record_source(
            alert=alert,
            patient_id=patient_id,
            source_type=source_type,
            source_id=source_id,
            source_key=source_key,
            source_label=title,
            value_display=content,
            baseline_display="",
            event_level=event_level,
            occurred_at=occurred_at,
            source_payload=source_payload,
        )

    @staticmethod
    def record_source(
        *,
        alert: PatientAlert,
        patient_id: int,
        source_type: str,
        source_id: int | None,
        source_key: str,
        source_label: str,
        value_display: str,
        baseline_display: str,
        event_level: int,
        occurred_at: datetime,
        source_payload: dict[str, Any],
    ) -> PatientAlertSource:
        source, _ = PatientAlertSource.objects.get_or_create(
            source_key=source_key,
            defaults={
                "alert": alert,
                "patient_id": patient_id,
                "source_type": source_type,
                "source_id": source_id,
                "source_label": source_label,
                "value_display": value_display,
                "baseline_display": baseline_display,
                "event_level": event_level,
                "occurred_at": occurred_at,
                "source_payload": source_payload or {},
            },
        )
        return source

    @classmethod
    def get_serialized_sources(cls, alert: PatientAlert) -> list[dict[str, str]]:
        sources = PatientAlertSource.objects.filter(alert=alert).order_by("-occurred_at", "-id")
        return [cls.serialize_source(source) for source in sources]

    @staticmethod
    def serialize_source(source: PatientAlertSource) -> dict[str, str]:
        return {
            "id": source.id,
            "source_type": source.source_type,
            "source_id": source.source_id,
            "source_label": source.source_label,
            "value_display": source.value_display,
            "baseline_display": source.baseline_display,
            "event_level": source.event_level,
            "event_level_display": _LEVEL_LABELS.get(source.event_level, ""),
            "occurred_at": PatientAlertSourceService._format_time(source.occurred_at),
        }

    @staticmethod
    def _get_metric_label(metric_type: str) -> str:
        try:
            return MetricType(metric_type).label
        except ValueError:
            return metric_type

    @staticmethod
    def _build_metric_baseline_display(*, patient: Any, metric_type: str) -> str:
        if metric_type == MetricType.BLOOD_PRESSURE:
            sbp = getattr(patient, "baseline_blood_pressure_sbp", None)
            dbp = getattr(patient, "baseline_blood_pressure_dbp", None)
            if sbp is not None and dbp is not None:
                return f"{sbp}/{dbp}"
            return ""
        if metric_type == MetricType.BLOOD_OXYGEN:
            baseline = getattr(patient, "baseline_blood_oxygen", None)
            return f"{baseline}%" if baseline is not None else ""
        if metric_type == MetricType.WEIGHT:
            baseline = getattr(patient, "baseline_weight", None)
            return f"{PatientAlertSourceService._format_decimal(baseline)}kg" if baseline is not None else ""
        return ""

    @staticmethod
    def _build_behavior_source_key(
        *,
        patient_id: int,
        source_type: str,
        source_id: int | None,
        payload: dict[str, Any],
    ) -> str:
        if source_id is not None:
            return f"{source_type}:{source_id}"
        date_value = payload.get("as_of_date") or payload.get("task_date") or timezone.localdate()
        return f"{source_type}:{patient_id}:{date_value}"

    @staticmethod
    def _format_decimal(value: Decimal | int | float | None) -> str:
        if value is None:
            return ""
        return f"{float(value):g}"

    @staticmethod
    def _format_time(value: datetime | date | None) -> str:
        if value is None:
            return ""
        if isinstance(value, datetime):
            if timezone.is_naive(value):
                value = timezone.make_aware(value, timezone.get_current_timezone())
            return timezone.localtime(value).strftime("%Y-%m-%d %H:%M")
        return value.strftime("%Y-%m-%d")
