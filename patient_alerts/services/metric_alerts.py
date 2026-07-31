from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Max, Min
from django.utils import timezone

from health_data.models import HealthMetric, MetricType
from health_data.utils import (
    evaluate_blood_ketone_level,
    evaluate_blood_pressure_level,
    evaluate_glucose_level,
    evaluate_spo2_level,
    evaluate_temperature_level,
    evaluate_uric_acid_level,
)
from patient_alerts.models import AlertEventType, AlertLevel, PatientAlert
from patient_alerts.services.alert_sources import PatientAlertSourceService
from patient_alerts.services.patient_alert import PatientAlertService
from users.models import PatientProfile


class MetricAlertService:
    """
    【功能说明】
    - 监测指标异常检测服务（血氧/体温/体重/血压）。
    - 满足轻/中/重条件时生成患者待办报警记录。
    """

    SPO2_CONFIRM_WINDOW_HOURS = 24
    SUPPORTED_METRIC_TYPES = {
        MetricType.BLOOD_OXYGEN,
        MetricType.BODY_TEMPERATURE,
        MetricType.WEIGHT,
        MetricType.BLOOD_PRESSURE,
        MetricType.BLOOD_GLUCOSE,
        MetricType.BLOOD_KETONE,
        MetricType.URIC_ACID,
    }

    @classmethod
    def process_metric(cls, metric: HealthMetric) -> PatientAlert | None:
        """
        根据单条指标记录进行异常判断并生成报警。

        【参数说明】
        - metric: HealthMetric，已落库的指标记录。

        【返回值说明】
        - PatientAlert | None：若未触发报警返回 None。
        """
        if not metric or metric.metric_type not in cls.SUPPORTED_METRIC_TYPES:
            return None

        patient = cls._get_patient(metric)

        alert = None
        if metric.metric_type == MetricType.BLOOD_OXYGEN:
            alert = cls._handle_spo2(metric, patient)
        elif metric.metric_type == MetricType.BODY_TEMPERATURE:
            alert = cls._handle_temperature(metric, patient)
        elif metric.metric_type == MetricType.WEIGHT:
            alert = cls._handle_weight(metric, patient)
        elif metric.metric_type == MetricType.BLOOD_PRESSURE:
            alert = cls._handle_blood_pressure(metric, patient)
        elif metric.metric_type == MetricType.BLOOD_GLUCOSE:
            alert = cls._handle_glucose(metric)
        elif metric.metric_type == MetricType.BLOOD_KETONE:
            alert = cls._handle_blood_ketone(metric)
        elif metric.metric_type == MetricType.URIC_ACID:
            alert = cls._handle_uric_acid(metric)

        if alert is None:
            cls.remove_metric(metric)
        return alert

    @classmethod
    def _handle_glucose(cls, metric: HealthMetric) -> PatientAlert | None:
        level = evaluate_glucose_level(
            metric.value_main,
            metric.measurement_context,
        )
        if level <= 0 or metric.value_main is None:
            return None
        context_label = metric.get_measurement_context_display() or "随机"
        return cls._create_alert(
            metric=metric,
            level=level,
            title="血糖异常",
            content=f"{context_label}血糖 {float(metric.value_main):g} mmol/L",
        )

    @classmethod
    def _handle_blood_ketone(cls, metric: HealthMetric) -> PatientAlert | None:
        level = evaluate_blood_ketone_level(metric.value_main)
        if level <= 0 or metric.value_main is None:
            return None
        return cls._create_alert(
            metric=metric,
            level=level,
            title="血酮异常",
            content=f"血酮 {float(metric.value_main):g} mmol/L",
        )

    @classmethod
    def _handle_uric_acid(cls, metric: HealthMetric) -> PatientAlert | None:
        level = evaluate_uric_acid_level(metric.value_main)
        if level <= 0 or metric.value_main is None:
            return None
        return cls._create_alert(
            metric=metric,
            level=level,
            title="尿酸异常",
            content=f"尿酸 {float(metric.value_main):g} μmol/L",
        )

    @staticmethod
    def _get_patient(metric: HealthMetric) -> PatientProfile:
        if getattr(metric, "patient", None):
            return metric.patient
        return PatientProfile.objects.get(id=metric.patient_id)

    @classmethod
    def _handle_spo2(
        cls, metric: HealthMetric, patient: PatientProfile
    ) -> PatientAlert | None:
        current = metric.value_main
        if current is None:
            return None
        measured_at = cls._resolve_metric_time(metric.measured_at)
        confirmed_drop = cls._is_spo2_confirmed_drop(
            metric=metric,
            baseline=patient.baseline_blood_oxygen,
            measured_at=measured_at,
        )
        level = evaluate_spo2_level(
            current_spo2=current,
            baseline_spo2=patient.baseline_blood_oxygen,
            confirmed_drop=confirmed_drop,
        )
        if level <= 0:
            return None
        content = cls._build_spo2_content(current, patient.baseline_blood_oxygen)
        return cls._create_alert(
            metric=metric,
            level=level,
            title="血氧异常",
            content=content,
        )

    @classmethod
    def _handle_temperature(
        cls, metric: HealthMetric, patient: PatientProfile
    ) -> PatientAlert | None:
        current = metric.value_main
        if current is None:
            return None

        measured_at = cls._resolve_metric_time(metric.measured_at)
        has_48h_persistent_high = cls._has_persistent_high_temp(
            patient_id=patient.id,
            end_time=measured_at,
            hours=48,
        )
        has_72h_persistent_high = cls._has_persistent_high_temp(
            patient_id=patient.id,
            end_time=measured_at,
            hours=72,
        )

        level = evaluate_temperature_level(
            current_temp=current,
            has_48h_persistent_high=has_48h_persistent_high,
            has_72h_persistent_high=has_72h_persistent_high,
        )
        if level <= 0:
            return None

        content = cls._build_temperature_content(
            current=current,
            has_48h=has_48h_persistent_high,
            has_72h=has_72h_persistent_high,
        )
        return cls._create_alert(
            metric=metric,
            level=level,
            title="体温异常",
            content=content,
        )

    @classmethod
    def _handle_weight(
        cls, metric: HealthMetric, patient: PatientProfile
    ) -> PatientAlert | None:
        current = metric.value_main
        if current is None:
            return None

        measured_at = cls._resolve_metric_time(metric.measured_at)
        short_term = cls._weight_change_over_3_days(
            patient_id=patient.id,
            current_time=measured_at,
        )
        long_term = cls._weight_change_over_180_days(
            patient=patient,
            current_time=measured_at,
            current_value=current,
        )

        if not (short_term or long_term):
            return None

        content = cls._build_weight_content(
            current=current,
            short_term=short_term,
            long_term=long_term,
        )
        return cls._create_alert(
            metric=metric,
            level=AlertLevel.MILD,
            title="体重异常",
            content=content,
        )

    @classmethod
    def _handle_blood_pressure(
        cls, metric: HealthMetric, patient: PatientProfile
    ) -> PatientAlert | None:
        sbp = metric.value_main
        dbp = metric.value_sub
        if sbp is None or dbp is None:
            return None

        sbp_lower, sbp_upper = cls._resolve_bp_range(
            patient.baseline_blood_pressure_sbp, default_lower=120, default_upper=140
        )
        dbp_lower, dbp_upper = cls._resolve_bp_range(
            patient.baseline_blood_pressure_dbp, default_lower=80, default_upper=90
        )
        level = evaluate_blood_pressure_level(
            sbp=sbp,
            dbp=dbp,
            sbp_lower=sbp_lower,
            sbp_upper=sbp_upper,
            dbp_lower=dbp_lower,
            dbp_upper=dbp_upper,
        )
        if level <= 0:
            return None

        content = cls._build_bp_content(
            sbp=sbp,
            dbp=dbp,
            sbp_base=patient.baseline_blood_pressure_sbp,
            dbp_base=patient.baseline_blood_pressure_dbp,
        )
        return cls._create_alert(
            metric=metric,
            level=level,
            title="血压异常",
            content=content,
        )

    @staticmethod
    def _resolve_metric_time(measured_at: datetime) -> datetime:
        if timezone.is_naive(measured_at):
            return timezone.make_aware(measured_at)
        return measured_at

    @classmethod
    def _is_spo2_confirmed_drop(
        cls,
        *,
        metric: HealthMetric,
        baseline: int | None,
        measured_at: datetime,
    ) -> bool:
        if baseline is None or baseline <= 0:
            return False
        if metric.value_main is None:
            return False
        baseline_val = Decimal(str(baseline))
        drop_ratio = (baseline_val - metric.value_main) / baseline_val
        if drop_ratio < Decimal("0.05"):
            return False

        start_time = measured_at - timedelta(hours=cls.SPO2_CONFIRM_WINDOW_HOURS)
        qs = (
            HealthMetric.objects.filter(
                patient_id=metric.patient_id,
                metric_type=MetricType.BLOOD_OXYGEN,
                measured_at__gte=start_time,
                measured_at__lte=measured_at,
            )
            .exclude(id=metric.id)
            .values_list("value_main", flat=True)
        )
        for value in qs:
            if value is None:
                continue
            ratio = (baseline_val - value) / baseline_val
            if ratio >= Decimal("0.05"):
                return True
        return False

    @staticmethod
    def _resolve_bp_range(
        baseline: int | None, *, default_lower: int, default_upper: int
    ) -> tuple[int, int]:
        if baseline is None:
            return default_lower, default_upper
        return baseline, baseline

    @classmethod
    def _has_persistent_high_temp(
        cls, *, patient_id: int, end_time: datetime, hours: int
    ) -> bool:
        start_time = end_time - timedelta(hours=hours)
        qs = (
            HealthMetric.objects.filter(
                patient_id=patient_id,
                metric_type=MetricType.BODY_TEMPERATURE,
                measured_at__gte=start_time,
                measured_at__lte=end_time,
            )
            .order_by("measured_at")
            .only("measured_at", "value_main")
        )
        first_time = qs.values_list("measured_at", flat=True).first()
        if not first_time:
            return False
        if end_time - first_time < timedelta(hours=hours):
            return False
        return not qs.filter(value_main__lt=Decimal("38")).exists()

    @classmethod
    def _weight_change_over_3_days(
        cls, *, patient_id: int, current_time: datetime
    ) -> bool:
        start_time = current_time - timedelta(days=3)
        values = HealthMetric.objects.filter(
            patient_id=patient_id,
            metric_type=MetricType.WEIGHT,
            measured_at__gte=start_time,
            measured_at__lte=current_time,
        ).aggregate(min_val=Min("value_main"), max_val=Max("value_main"))

        min_val = values.get("min_val")
        max_val = values.get("max_val")
        if min_val is None or max_val is None:
            return False
        return (max_val - min_val) > Decimal("2")

    @classmethod
    def _weight_change_over_180_days(
        cls,
        *,
        patient: PatientProfile,
        current_time: datetime,
        current_value: Decimal,
    ) -> bool:
        base = patient.baseline_weight
        if base is None:
            start_time = current_time - timedelta(days=180)
            base = (
                HealthMetric.objects.filter(
                    patient_id=patient.id,
                    metric_type=MetricType.WEIGHT,
                    measured_at__gte=start_time,
                    measured_at__lte=current_time,
                )
                .order_by("measured_at")
                .values_list("value_main", flat=True)
                .first()
            )
        if base is None or base == 0:
            return False
        return (abs(current_value - base) / base) > Decimal("0.05")

    @staticmethod
    def _build_spo2_content(
        current: Decimal, baseline: int | None
    ) -> str:
        if baseline:
            return f"血氧 {int(current)}%（基线 {baseline}%）"
        return f"血氧 {int(current)}%"

    @staticmethod
    def _build_temperature_content(
        *, current: Decimal, has_48h: bool, has_72h: bool
    ) -> str:
        note = ""
        if has_72h:
            note = "，连续72小时≥38℃"
        elif has_48h:
            note = "，连续48小时≥38℃"
        return f"体温 {float(current):g}℃{note}"

    @staticmethod
    def _build_weight_content(
        *, current: Decimal, short_term: bool, long_term: bool
    ) -> str:
        reasons = []
        if short_term:
            reasons.append("3天变化>2kg")
        if long_term:
            reasons.append("180天变化>5%")
        reason_text = "、".join(reasons) if reasons else ""
        if reason_text:
            return f"体重 {float(current):g}kg（{reason_text}）"
        return f"体重 {float(current):g}kg"

    @staticmethod
    def _build_bp_content(
        *, sbp: Decimal, dbp: Decimal, sbp_base: int | None, dbp_base: int | None
    ) -> str:
        base_text = ""
        if sbp_base and dbp_base:
            base_text = f"（基线 {sbp_base}/{dbp_base}）"
        return f"血压 {int(sbp)}/{int(dbp)}{base_text}"

    @classmethod
    def _create_alert(
        cls,
        *,
        metric: HealthMetric,
        level: int,
        title: str,
        content: str,
    ) -> PatientAlert:
        payload: dict[str, Any] = {
            "metric_id": metric.id,
            "metric_type": metric.metric_type,
            "value_main": str(metric.value_main) if metric.value_main is not None else None,
            "value_sub": str(metric.value_sub) if metric.value_sub is not None else None,
            "measured_at": metric.measured_at.isoformat(),
            "measurement_context": metric.measurement_context,
        }
        alert = PatientAlertService.create_or_update_alert(
            patient_id=metric.patient_id,
            event_type=AlertEventType.DATA,
            event_level=level,
            event_title=title,
            event_content=content,
            event_time=metric.measured_at,
            source_type="metric",
            source_id=metric.id,
            source_payload=payload,
            dedup_filters={
                "event_title": title,
                "source_type": "metric",
            },
        )
        PatientAlertSourceService.record_metric_source(
            alert=alert,
            metric=metric,
            event_level=level,
            source_payload=payload,
        )
        cls._refresh_alert_from_sources(alert)
        return alert

    @classmethod
    def remove_metric(cls, metric: HealthMetric) -> None:
        """移除指标对应的异常来源并重算聚合预警。"""
        source = (
            PatientAlertSourceService.get_metric_source(metric.id)
        )
        if source is None:
            return
        alert = source.alert
        source.delete()
        cls._refresh_alert_from_sources(alert)

    @staticmethod
    def _refresh_alert_from_sources(alert: PatientAlert) -> None:
        sources = alert.sources.all()
        if not sources.exists():
            if alert.is_active:
                alert.is_active = False
                alert.save(update_fields=["is_active"])
            return

        latest = sources.order_by("-occurred_at", "-id").first()
        max_level = sources.aggregate(value=Max("event_level"))["value"]
        alert.is_active = True
        alert.event_level = max_level
        alert.event_time = latest.occurred_at
        alert.source_id = latest.source_id
        alert.source_payload = latest.source_payload
        alert.event_content = latest.value_display
        alert.save(
            update_fields=[
                "is_active",
                "event_level",
                "event_time",
                "source_id",
                "source_payload",
                "event_content",
            ]
        )
