from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Iterable

from django.db.models import Count, Q
from django.utils import timezone

from core.models import DailyTask, MonitoringTemplate, choices as core_choices
from health_data.models import MetricType
from patient_alerts.models import AlertEventType, AlertLevel, AlertStatus, PatientAlert
from patient_alerts.services.patient_alert import PatientAlertService
from users.models import PatientProfile


class BehaviorAlertService:
    """
    【功能说明】
    - 行为异常检测与报警生成：
      用药未完成、监测未完成、随访过期、复查过期。
    - 提供批量扫描入口，供定时任务调用。
    """

    MAX_CONSECUTIVE_DAYS = 7

    @classmethod
    def run(
        cls,
        *,
        as_of_date: date | None = None,
        patient_ids: Iterable[int] | None = None,
    ) -> list[PatientAlert]:
        """
        批量扫描患者行为异常并生成报警。

        【参数说明】
        - as_of_date: date | None，默认昨天，用于连续未完成统计。
        - patient_ids: 可选患者 ID 列表；为空则扫描所有有效患者。

        【返回值说明】
        - List[PatientAlert]：本次触发/更新的报警列表。
        """
        if as_of_date is None:
            as_of_date = timezone.localdate() - timedelta(days=1)

        patients = PatientProfile.objects.filter(is_active=True)
        if patient_ids:
            patients = patients.filter(id__in=list(patient_ids))

        template_map = cls._load_monitoring_templates()

        alerts: list[PatientAlert] = []
        for patient in patients:
            alerts.extend(cls._process_medication(patient, as_of_date))
            alerts.extend(cls._process_monitoring(patient, as_of_date, template_map))
            alerts.extend(
                cls._process_overdue_tasks(
                    patient,
                    task_type=core_choices.PlanItemCategory.QUESTIONNAIRE,
                    source_type="behavior_questionnaire",
                    title_prefix="随访过期",
                )
            )
            alerts.extend(
                cls._process_overdue_tasks(
                    patient,
                    task_type=core_choices.PlanItemCategory.CHECKUP,
                    source_type="behavior_checkup",
                    title_prefix="复查过期",
                )
            )
        return alerts

    @classmethod
    def _process_medication(
        cls, patient: PatientProfile, as_of_date: date
    ) -> list[PatientAlert]:
        missed_count = cls._count_consecutive_missed_days(
            patient=patient,
            task_type=core_choices.PlanItemCategory.MEDICATION,
            as_of_date=as_of_date,
            template_id=None,
        )
        level = cls._resolve_level_by_missed(missed_count)
        if not level:
            return []

        title = "用药未完成"
        content = f"连续{missed_count}天未完成用药任务"
        event_time = cls._resolve_event_time(as_of_date)
        alert = cls._upsert_behavior_alert(
            patient_id=patient.id,
            source_type="behavior_medication",
            source_id=None,
            level=level,
            title=title,
            content=content,
            event_time=event_time,
            payload={
                "missed_days": missed_count,
                "as_of_date": str(as_of_date),
            },
        )
        return [alert] if alert else []

    @classmethod
    def _process_monitoring(
        cls,
        patient: PatientProfile,
        as_of_date: date,
        template_map: dict[int, dict[str, Any]],
    ) -> list[PatientAlert]:
        if not template_map:
            return []

        alerts: list[PatientAlert] = []
        for template_id, meta in template_map.items():
            missed_count = cls._count_consecutive_missed_days(
                patient=patient,
                task_type=core_choices.PlanItemCategory.MONITORING,
                as_of_date=as_of_date,
                template_id=template_id,
            )
            level = cls._resolve_level_by_missed(missed_count)
            if not level:
                continue

            metric_name = meta.get("name") or "监测"
            metric_code = meta.get("code") or ""
            title = f"监测未完成-{metric_name}"
            content = f"连续{missed_count}天未完成{metric_name}监测"
            event_time = cls._resolve_event_time(as_of_date)
            alert = cls._upsert_behavior_alert(
                patient_id=patient.id,
                source_type=f"behavior_monitoring:{metric_code}",
                source_id=None,
                level=level,
                title=title,
                content=content,
                event_time=event_time,
                payload={
                    "metric_code": metric_code,
                    "missed_days": missed_count,
                    "as_of_date": str(as_of_date),
                },
            )
            if alert:
                alerts.append(alert)
        return alerts

    @classmethod
    def _process_overdue_tasks(
        cls,
        patient: PatientProfile,
        *,
        task_type: int,
        source_type: str,
        title_prefix: str,
    ) -> list[PatientAlert]:
        today = timezone.localdate()
        tasks = (
            DailyTask.objects.filter(
                patient_id=patient.id,
                task_type=task_type,
                status__in=[
                    core_choices.TaskStatus.PENDING,
                    core_choices.TaskStatus.TERMINATED,
                    core_choices.TaskStatus.NOT_STARTED,
                ],
                task_date__lte=today - timedelta(days=2),
            )
            .only("id", "task_date", "title")
            .order_by("task_date")
        )
        alerts: list[PatientAlert] = []
        for task in tasks:
            days_since_due = (today - task.task_date).days
            level = cls._resolve_level_by_overdue(days_since_due)
            if not level:
                continue

            title = f"{title_prefix}"
            content = (
                f"{task.title}已逾期{days_since_due}天"
                if task.title
                else f"计划任务已逾期{days_since_due}天"
            )
            event_time = cls._resolve_overdue_event_time(task.task_date, level)
            alert = cls._upsert_behavior_alert(
                patient_id=patient.id,
                source_type=source_type,
                source_id=task.id,
                level=level,
                title=title,
                content=content,
                event_time=event_time,
                payload={
                    "task_id": task.id,
                    "task_date": str(task.task_date),
                    "days_overdue": days_since_due,
                },
            )
            if alert:
                alerts.append(alert)
        return alerts

    @classmethod
    def _count_consecutive_missed_days(
        cls,
        *,
        patient: PatientProfile,
        task_type: int,
        as_of_date: date,
        template_id: int | None,
    ) -> int:
        start_date = as_of_date - timedelta(days=cls.MAX_CONSECUTIVE_DAYS - 1)
        qs = DailyTask.objects.filter(
            patient_id=patient.id,
            task_type=task_type,
            task_date__range=(start_date, as_of_date),
        )
        if template_id is not None:
            qs = qs.filter(plan_item__template_id=template_id)

        summary = (
            qs.values("task_date")
            .annotate(
                pending=Count(
                    "id",
                    filter=Q(
                        status__in=[
                            core_choices.TaskStatus.PENDING,
                            core_choices.TaskStatus.TERMINATED,
                            core_choices.TaskStatus.NOT_STARTED,
                        ]
                    ),
                )
            )
        )
        pending_map = {row["task_date"]: row["pending"] for row in summary}

        missed = 0
        for offset in range(cls.MAX_CONSECUTIVE_DAYS):
            target_date = as_of_date - timedelta(days=offset)
            if target_date not in pending_map:
                break
            if pending_map[target_date] <= 0:
                break
            missed += 1
        return missed

    @staticmethod
    def _resolve_level_by_missed(missed_days: int) -> int | None:
        if missed_days >= 7:
            return AlertLevel.SEVERE
        if missed_days >= 3:
            return AlertLevel.MODERATE
        if missed_days >= 1:
            return AlertLevel.MILD
        return None

    @staticmethod
    def _resolve_level_by_overdue(days_since_due: int) -> int | None:
        if days_since_due >= 7:
            return AlertLevel.SEVERE
        if days_since_due >= 4:
            return AlertLevel.MODERATE
        if days_since_due >= 2:
            return AlertLevel.MILD
        return None

    @staticmethod
    def _resolve_event_time(as_of_date: date) -> datetime:
        event_time = datetime.combine(as_of_date, datetime.min.time())
        if timezone.is_aware(timezone.now()):
            event_time = timezone.make_aware(event_time)
        return event_time

    @staticmethod
    def _resolve_overdue_event_time(task_date: date, level: int) -> datetime:
        offset = 2
        if level == AlertLevel.MODERATE:
            offset = 4
        elif level == AlertLevel.SEVERE:
            offset = 7
        event_date = task_date + timedelta(days=offset)
        event_time = datetime.combine(event_date, datetime.min.time())
        if timezone.is_aware(timezone.now()):
            event_time = timezone.make_aware(event_time)
        return event_time

    @staticmethod
    def _load_monitoring_templates() -> dict[int, dict[str, Any]]:
        templates = MonitoringTemplate.objects.filter(
            code__in=[
                MetricType.BLOOD_PRESSURE,
                MetricType.BLOOD_OXYGEN,
                MetricType.HEART_RATE,
                MetricType.STEPS,
                MetricType.WEIGHT,
                MetricType.BODY_TEMPERATURE,
            ]
        ).only("id", "code", "name")
        return {
            template.id: {"code": template.code, "name": template.name}
            for template in templates
        }

    @classmethod
    def _upsert_behavior_alert(
        cls,
        *,
        patient_id: int,
        source_type: str,
        source_id: int | None,
        level: int,
        title: str,
        content: str,
        event_time: datetime,
        payload: dict[str, Any],
    ) -> PatientAlert | None:
        qs = PatientAlert.objects.filter(
            patient_id=patient_id,
            event_type=AlertEventType.BEHAVIOR,
            source_type=source_type,
            is_active=True,
            status__in=[AlertStatus.PENDING, AlertStatus.ESCALATED],
        )
        if source_id is None:
            qs = qs.filter(source_id__isnull=True)
        else:
            qs = qs.filter(source_id=source_id)
        existing = qs.order_by("-event_time", "-id").first()
        if not existing:
            return PatientAlertService.create_alert(
                patient_id=patient_id,
                event_type=AlertEventType.BEHAVIOR,
                event_level=level,
                event_title=title,
                event_content=content,
                event_time=event_time,
                source_type=source_type,
                source_id=source_id,
                source_payload=payload,
            )

        updated = False
        new_level = max(existing.event_level, level)
        if new_level != existing.event_level:
            existing.event_level = new_level
            updated = True
        if event_time and event_time > existing.event_time:
            existing.event_time = event_time
            updated = True
        if updated or existing.event_content != content:
            existing.event_title = title
            existing.event_content = content
            existing.source_payload = payload
            existing.save(
                update_fields=[
                    "event_level",
                    "event_time",
                    "event_title",
                    "event_content",
                    "source_payload",
                ]
            )
            return existing

        return existing
