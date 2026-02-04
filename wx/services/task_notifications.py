"""每日任务相关的模板消息（模拟发送）。"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, Iterable, List, Set

from django.db import transaction
from django.db.models import Prefetch
from django.utils import timezone

from business_support.models import Device
from business_support.service.device import SmartWatchService
from core.models import DailyTask, choices as core_choices
from core.service.tasks import refresh_task_statuses
from users import choices as user_choices
from users.models import PatientProfile, PatientRelation
from wx.models import SendMessageLog

_TASK_TYPES = (
    core_choices.PlanItemCategory.MEDICATION,
    core_choices.PlanItemCategory.CHECKUP,
    core_choices.PlanItemCategory.MONITORING,
    core_choices.PlanItemCategory.QUESTIONNAIRE,
)

_CREATED_MESSAGE_BY_TYPE = {
    core_choices.PlanItemCategory.MEDICATION: "已为您生成今日用药计划",
    core_choices.PlanItemCategory.CHECKUP: "已为您生成今日复查计划",
    core_choices.PlanItemCategory.MONITORING: "已为您生成今日监测计划",
    core_choices.PlanItemCategory.QUESTIONNAIRE: "已为您生成今日随访计划",
}
_REMINDER_MESSAGE_BY_TYPE = {
    core_choices.PlanItemCategory.MEDICATION: "您的用药任务未完成",
    core_choices.PlanItemCategory.CHECKUP: "您的复查任务未完成",
    core_choices.PlanItemCategory.MONITORING: "您的监测任务未完成",
    core_choices.PlanItemCategory.QUESTIONNAIRE: "您的随访任务未完成",
}
_MULTI_TASK_MESSAGE = {
    SendMessageLog.Scene.DAILY_TASK_CREATED: "已为您生成今日监测任务",
    SendMessageLog.Scene.DAILY_TASK_REMINDER: "您的今日监测任务未完成",
}
_WATCH_TITLE_BY_TYPE = {
    core_choices.PlanItemCategory.MEDICATION: "用药提醒",
    core_choices.PlanItemCategory.CHECKUP: "复查提醒",
    core_choices.PlanItemCategory.MONITORING: "监测提醒",
    core_choices.PlanItemCategory.QUESTIONNAIRE: "随访提醒",
}
_WATCH_MULTI_TITLE = "今日任务"


def send_daily_task_creation_messages(task_date: date | None = None) -> int:
    """发送每日任务生成提醒（早上 6 点）。"""
    if task_date is None:
        task_date = timezone.localdate()
    return _send_task_messages(
        task_date=task_date,
        scene=SendMessageLog.Scene.DAILY_TASK_CREATED,
        pending_only=False,
    )


def send_daily_task_reminder_messages(as_of_date: date | None = None) -> int:
    """发送未完成提醒（下午 6 点）。"""
    if as_of_date is None:
        as_of_date = timezone.localdate()
    refresh_task_statuses(as_of_date=as_of_date)
    return _send_task_messages(
        task_date=as_of_date,
        scene=SendMessageLog.Scene.DAILY_TASK_REMINDER,
        pending_only=True,
    )


def _send_task_messages(
    *,
    task_date: date,
    scene: str,
    pending_only: bool,
) -> int:
    task_types_by_patient = _load_task_types_by_patient(
        task_date=task_date,
        pending_only=pending_only,
    )
    if not task_types_by_patient:
        return 0

    patient_ids = list(task_types_by_patient.keys())
    patients = _load_patients(patient_ids)
    recipient_map = _collect_recipients(patients)
    existing_pairs = (
        _load_existing_pairs(
            scene=scene,
            task_date=task_date,
            recipient_map=recipient_map,
        )
        if recipient_map
        else set()
    )
    existing_watch_patients = _load_existing_watch_patients(
        scene=scene,
        task_date=task_date,
    )

    logs_to_create: List[SendMessageLog] = []
    for patient in patients:
        task_types = task_types_by_patient.get(patient.id)
        if not task_types:
            continue
        content = _resolve_message(task_types=task_types, scene=scene)
        if not content:
            continue

        payload = {
            "task_date": str(task_date),
            "task_types": sorted(int(task_type) for task_type in task_types),
        }
        watch_title = _resolve_watch_title(task_types=task_types)
        _maybe_send_watch_message(
            patient=patient,
            scene=scene,
            task_date=task_date,
            title=watch_title,
            content=content,
            payload=payload,
            existing_watch_patients=existing_watch_patients,
            logs_to_create=logs_to_create,
        )

        recipients = recipient_map.get(patient.id, [])
        if not recipients:
            continue
        for user in recipients:
            pair = (patient.id, user.id)
            if pair in existing_pairs:
                continue
            logs_to_create.append(
                SendMessageLog(
                    patient=patient,
                    user=user,
                    openid=user.wx_openid or "",
                    channel=SendMessageLog.Channel.WECHAT,
                    scene=scene,
                    biz_date=task_date,
                    content=content,
                    payload=payload,
                    is_success=True,
                    error_message="",
                )
            )

    if not logs_to_create:
        return 0

    with transaction.atomic():
        SendMessageLog.objects.bulk_create(logs_to_create, batch_size=200)

    return len(logs_to_create)


def _load_task_types_by_patient(
    *,
    task_date: date,
    pending_only: bool,
) -> Dict[int, Set[int]]:
    tasks = DailyTask.objects.filter(
        patient__is_active=True,
        task_type__in=_TASK_TYPES,
    )
    if pending_only:
        tasks = tasks.filter(
            status=core_choices.TaskStatus.PENDING,
            task_date__lte=task_date,
        )
    else:
        tasks = tasks.filter(task_date=task_date).exclude(
            status__in=[
                core_choices.TaskStatus.NOT_STARTED,
                core_choices.TaskStatus.TERMINATED,
            ]
        )

    pairs = tasks.values_list("patient_id", "task_type").distinct()
    task_types_by_patient: Dict[int, Set[int]] = {}
    for patient_id, task_type in pairs:
        task_types_by_patient.setdefault(patient_id, set()).add(int(task_type))
    return task_types_by_patient


def _load_patients(patient_ids: Iterable[int]) -> List[PatientProfile]:
    relations_qs = (
        PatientRelation.objects.filter(
            is_active=True,
            receive_alert_msg=True,
        )
        .exclude(relation_type=user_choices.RelationType.SELF)
        .select_related("user")
    )
    return list(
        PatientProfile.objects.filter(id__in=list(patient_ids), is_active=True)
        .select_related("user")
        .prefetch_related(
            Prefetch("relations", queryset=relations_qs, to_attr="alert_relations"),
            Prefetch(
                "devices",
                queryset=Device.objects.filter(
                    is_active=True,
                    device_type=Device.DeviceType.WATCH,
                ).order_by("-bind_at"),
                to_attr="watch_devices",
            ),
        )
    )


def _collect_recipients(
    patients: Iterable[PatientProfile],
) -> Dict[int, List]:
    recipient_map: Dict[int, List] = {}
    for patient in patients:
        recipients = []
        user = patient.user
        if (
            user
            and user.is_active
            and user.is_subscribe
            and getattr(user, "is_receive_wechat_message", True)
            and user.wx_openid
        ):
            recipients.append(user)
        for relation in getattr(patient, "alert_relations", []) or []:
            relation_user = relation.user
            if not relation_user:
                continue
            if not relation_user.is_active:
                continue
            if not relation_user.is_subscribe:
                continue
            if not getattr(relation_user, "is_receive_wechat_message", True):
                continue
            if not relation_user.wx_openid:
                continue
            recipients.append(relation_user)

        seen = set()
        unique_recipients = []
        for recipient in recipients:
            if recipient.id in seen:
                continue
            seen.add(recipient.id)
            unique_recipients.append(recipient)

        if unique_recipients:
            recipient_map[patient.id] = unique_recipients
    return recipient_map


def _load_existing_pairs(
    *,
    scene: str,
    task_date: date,
    recipient_map: Dict[int, List],
) -> Set[tuple[int, int]]:
    if not recipient_map:
        return set()
    patient_ids = list(recipient_map.keys())
    user_ids: Set[int] = set()
    for users in recipient_map.values():
        for user in users:
            user_ids.add(user.id)
    if not user_ids:
        return set()
    pairs = SendMessageLog.objects.filter(
        scene=scene,
        biz_date=task_date,
        channel=SendMessageLog.Channel.WECHAT,
        is_success=True,
        patient_id__in=patient_ids,
        user_id__in=list(user_ids),
    ).values_list("patient_id", "user_id")
    return set(pairs)


def _load_existing_watch_patients(
    *,
    scene: str,
    task_date: date,
) -> Set[int]:
    return set(
        SendMessageLog.objects.filter(
            scene=scene,
            biz_date=task_date,
            channel=SendMessageLog.Channel.WATCH,
            is_success=True,
        ).values_list("patient_id", flat=True)
    )


def _resolve_message(*, task_types: Set[int], scene: str) -> str | None:
    if not task_types:
        return None
    if len(task_types) >= 2:
        return _MULTI_TASK_MESSAGE.get(scene)
    task_type = next(iter(task_types))
    if scene == SendMessageLog.Scene.DAILY_TASK_CREATED:
        return _CREATED_MESSAGE_BY_TYPE.get(task_type)
    if scene == SendMessageLog.Scene.DAILY_TASK_REMINDER:
        return _REMINDER_MESSAGE_BY_TYPE.get(task_type)
    return None


def _resolve_watch_title(*, task_types: Set[int]) -> str:
    if not task_types:
        return _WATCH_MULTI_TITLE
    if len(task_types) >= 2:
        return _WATCH_MULTI_TITLE
    task_type = next(iter(task_types))
    return _WATCH_TITLE_BY_TYPE.get(task_type, _WATCH_MULTI_TITLE)


def _maybe_send_watch_message(
    *,
    patient: PatientProfile,
    scene: str,
    task_date: date,
    title: str,
    content: str,
    payload: Dict[str, Any],
    existing_watch_patients: Set[int],
    logs_to_create: List[SendMessageLog],
) -> None:
    if patient.id in existing_watch_patients:
        return
    owner = getattr(patient, "user", None)
    if owner and not getattr(owner, "is_receive_watch_message", True):
        return

    device = None
    watch_devices = getattr(patient, "watch_devices", None)
    if watch_devices:
        device = watch_devices[0]
    else:
        device = (
            patient.devices.filter(
                is_active=True,
                device_type=Device.DeviceType.WATCH,
            )
            .order_by("-bind_at")
            .first()
        )
    if not device:
        return

    device_no = device.imei or device.sn
    if not device_no:
        return

    success, result = SmartWatchService.send_message(device_no, title, content)
    if not success:
        return

    log_payload = dict(payload)
    log_payload.update(
        {
            "device_no": device_no,
            "msg_id": result,
        }
    )
    logs_to_create.append(
        SendMessageLog(
            patient=patient,
            user=None,
            openid="",
            channel=SendMessageLog.Channel.WATCH,
            scene=scene,
            biz_date=task_date,
            content=content,
            payload=log_payload,
            is_success=True,
            error_message="",
        )
    )
