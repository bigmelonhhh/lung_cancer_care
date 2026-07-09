"""每日任务相关的模板消息（公众号 + 手表）。"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Set

from django.conf import settings
from django.db import transaction
from django.db.models import Prefetch
from django.utils import timezone

from business_support.models import Device
from business_support.services.device_integrations.hrt import HrtWatchService
from core.models import DailyTask, choices as core_choices
from core.service.tasks import refresh_task_statuses
from users import choices as user_choices
from users.models import PatientProfile, PatientRelation
from wx.models import SendMessageLog
from wx.services.oauth import generate_menu_auth_url
from wx.services.templates import send_template_message

logger = logging.getLogger(__name__)

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
_ADVANCE_REMINDER_DAYS_BY_TYPE = {
    core_choices.PlanItemCategory.CHECKUP: (1, 3),
}
_MULTI_TASK_MESSAGE = {
    SendMessageLog.Scene.DAILY_TASK_CREATED: "已为您生成今日监测任务",
    SendMessageLog.Scene.DAILY_TASK_REMINDER: "您的今日监测任务未完成",
}
_MIXED_UPCOMING_REMINDER_MESSAGE = "您有近期任务需要关注"
_WATCH_TITLE_BY_TYPE = {
    core_choices.PlanItemCategory.MEDICATION: "用药提醒",
    core_choices.PlanItemCategory.CHECKUP: "复查提醒",
    core_choices.PlanItemCategory.MONITORING: "监测提醒",
    core_choices.PlanItemCategory.QUESTIONNAIRE: "随访提醒",
}
_WATCH_MULTI_TITLE = "今日任务"
_DASHBOARD_VIEW_NAME = "web_patient:patient_home"
_TEMPLATE_TIME_FORMAT = "%Y-%m-%d %H:%M"


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
    reminder_items_by_patient: Dict[int, List[Dict[str, Any]]] = {}
    if pending_only:
        reminder_items_by_patient = _load_reminder_items_by_patient(task_date)
        task_types_by_patient = {
            patient_id: {int(item["task_type"]) for item in items}
            for patient_id, items in reminder_items_by_patient.items()
        }
    else:
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
    template_id = _get_wechat_template_id()
    dashboard_url = _get_dashboard_url()
    send_time = timezone.localtime()

    logs_to_create: List[SendMessageLog] = []
    for patient in patients:
        task_types = task_types_by_patient.get(patient.id)
        if not task_types:
            continue
        reminder_items = reminder_items_by_patient.get(patient.id, [])
        content = (
            _resolve_reminder_message(reminder_items)
            if pending_only
            else _resolve_message(task_types=task_types, scene=scene)
        )
        if not content:
            continue

        payload = _build_message_payload(
            task_date=task_date,
            task_types=task_types,
            reminder_items=reminder_items,
        )
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
            template_data = _build_template_data(content=content, send_time=send_time)
            ok, error = _send_wechat_template_message(
                openid=user.wx_openid or "",
                template_id=template_id,
                data=template_data,
                url=dashboard_url,
            )
            wechat_payload = dict(payload)
            wechat_payload.update(
                {
                    "template_id": template_id,
                    "template_data": template_data,
                    "url": dashboard_url,
                }
            )
            logs_to_create.append(
                SendMessageLog(
                    patient=patient,
                    user=user,
                    openid=user.wx_openid or "",
                    channel=SendMessageLog.Channel.WECHAT,
                    scene=scene,
                    biz_date=task_date,
                    content=content,
                    payload=wechat_payload,
                    is_success=ok,
                    error_message="" if ok else str(error or ""),
                )
            )

    if not logs_to_create:
        return 0

    with transaction.atomic():
        SendMessageLog.objects.bulk_create(logs_to_create, batch_size=200)

    return len(logs_to_create)


def _build_message_payload(
    *,
    task_date: date,
    task_types: Set[int],
    reminder_items: List[Dict[str, Any]],
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "task_date": str(task_date),
        "task_types": sorted(int(task_type) for task_type in task_types),
    }
    if reminder_items:
        payload["reminder_date"] = str(task_date)
        payload["tasks"] = [
            {
                "task_id": item["task_id"],
                "task_date": str(item["task_date"]),
                "task_type": int(item["task_type"]),
                "lead_days": item["lead_days"],
            }
            for item in reminder_items
        ]
    return payload


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


def _load_reminder_items_by_patient(as_of_date: date) -> Dict[int, List[Dict[str, Any]]]:
    due_tasks = DailyTask.objects.filter(
        patient__is_active=True,
        task_type__in=_TASK_TYPES,
        status=core_choices.TaskStatus.PENDING,
        task_date__lte=as_of_date,
    )

    reminder_items_by_patient: Dict[int, List[Dict[str, Any]]] = {}
    for task_id, patient_id, task_type, task_date_value in due_tasks.order_by(
        "patient_id", "task_date", "id"
    ).values_list("id", "patient_id", "task_type", "task_date"):
        reminder_items_by_patient.setdefault(patient_id, []).append(
            {
                "task_id": task_id,
                "task_type": int(task_type),
                "task_date": task_date_value,
                "lead_days": 0,
            }
        )

    for task_type, lead_days_list in _ADVANCE_REMINDER_DAYS_BY_TYPE.items():
        target_dates = [as_of_date + timedelta(days=days) for days in lead_days_list]
        future_tasks = DailyTask.objects.filter(
            patient__is_active=True,
            task_type=task_type,
            task_date__in=target_dates,
            status__in=[
                core_choices.TaskStatus.PENDING,
                core_choices.TaskStatus.NOT_STARTED,
            ],
        )
        for task_id, patient_id, task_date_value in future_tasks.order_by(
            "patient_id", "task_date", "id"
        ).values_list("id", "patient_id", "task_date"):
            lead_days = (task_date_value - as_of_date).days
            reminder_items_by_patient.setdefault(patient_id, []).append(
                {
                    "task_id": task_id,
                    "task_type": int(task_type),
                    "task_date": task_date_value,
                    "lead_days": lead_days,
                }
            )

    return reminder_items_by_patient


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


def _resolve_reminder_message(reminder_items: List[Dict[str, Any]]) -> str | None:
    if not reminder_items:
        return None

    task_types = {int(item["task_type"]) for item in reminder_items}
    has_due_task = any(item["lead_days"] == 0 for item in reminder_items)
    has_future_task = any(item["lead_days"] > 0 for item in reminder_items)
    if has_due_task and has_future_task:
        return _MIXED_UPCOMING_REMINDER_MESSAGE
    if has_due_task:
        return _resolve_message(
            task_types=task_types,
            scene=SendMessageLog.Scene.DAILY_TASK_REMINDER,
        )

    if task_types == {core_choices.PlanItemCategory.CHECKUP}:
        lead_days = sorted({item["lead_days"] for item in reminder_items})
        if len(lead_days) == 1:
            lead_day = lead_days[0]
            if lead_day == 1:
                return "您有明天的复查任务"
            return f"您有{lead_day}天后的复查任务"
        return "您有近期复查任务"

    return _MIXED_UPCOMING_REMINDER_MESSAGE


def _resolve_watch_title(*, task_types: Set[int]) -> str:
    if not task_types:
        return _WATCH_MULTI_TITLE
    if len(task_types) >= 2:
        return _WATCH_MULTI_TITLE
    task_type = next(iter(task_types))
    return _WATCH_TITLE_BY_TYPE.get(task_type, _WATCH_MULTI_TITLE)


def _get_wechat_template_id() -> str:
    return (getattr(settings, "WECHAT_DAILY_TASK_TEMPLATE_ID", "") or "").strip()


def _get_dashboard_url() -> str | None:
    try:
        return generate_menu_auth_url(_DASHBOARD_VIEW_NAME)
    except Exception as exc:  # pragma: no cover - 依赖配置
        logger.error("Generate dashboard auth url failed: %s", exc)
        return None


def _build_template_data(*, content: str, send_time) -> Dict[str, Dict[str, str]]:
    time_value = send_time.strftime(_TEMPLATE_TIME_FORMAT)
    return {
        "time4": {"value": time_value},
        "thing59": {"value": content},
    }


def _send_wechat_template_message(
    *,
    openid: str,
    template_id: str,
    data: Dict[str, Dict[str, str]],
    url: str | None,
) -> tuple[bool, str | None]:
    if not openid:
        return False, "缺少 openid"
    if not template_id:
        return False, "缺少模板ID"
    if not url:
        return False, "缺少跳转链接"
    try:
        result = send_template_message(openid, template_id, data, url=url)
        if isinstance(result, dict):
            errcode = result.get("errcode")
            if errcode not in (None, 0):
                return False, result.get("errmsg") or f"errcode={errcode}"
        return True, None
    except Exception as exc:  # pragma: no cover - 网络/配置异常
        return False, str(exc)


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

    success, result = HrtWatchService.send_message(device_no, title, content)
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
