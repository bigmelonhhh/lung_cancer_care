"""聊天未读提醒（公众号推送）。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Set, Tuple

from django.utils import timezone
from django_redis import get_redis_connection

from chat.models import (
    ConversationReadState,
    ConversationType,
    Message,
    MessageSenderRole,
)
from wx.models import SendMessageLog


_DEFAULT_DELAY_SECONDS = 30
_DEFAULT_LIMIT = 200
_UNREAD_CONTENT = "您有新的医生消息，请及时查看。"


def schedule_chat_unread_notification(
    message_id: int,
    *,
    delay_seconds: int = _DEFAULT_DELAY_SECONDS,
) -> None:
    """延迟触发未读提醒任务（Celery）。"""
    if not message_id:
        return
    delay_seconds = max(0, int(delay_seconds))
    try:
        from wx.tasks import send_chat_unread_notification_task

        send_chat_unread_notification_task.apply_async(
            args=[message_id],
            countdown=delay_seconds,
        )
    except Exception:  # pragma: no cover - 任务系统不可用时容错
        return


def send_chat_unread_notification_for_message(
    message_id: int,
    *,
    as_of: datetime | None = None,
    delay_seconds: int = _DEFAULT_DELAY_SECONDS,
) -> bool:
    """针对单条消息判断未读并推送。"""
    if not message_id:
        return False
    if as_of is None:
        as_of = timezone.now()
    delay_seconds = max(0, int(delay_seconds))

    message = (
        Message.objects.filter(pk=message_id)
        .select_related("conversation__patient__user")
        .first()
    )
    if not message or not message.conversation:
        return False
    if message.conversation.type != ConversationType.PATIENT_STUDIO:
        return False
    if message.sender_role_snapshot in (
        MessageSenderRole.PATIENT,
        MessageSenderRole.FAMILY,
    ):
        return False

    if message.created_at:
        threshold = message.created_at + timedelta(seconds=delay_seconds)
        if as_of < threshold:
            return False

    patient = message.conversation.patient
    user = patient.user if patient else None
    if (
        not user
        or not user.is_active
        or not user.is_subscribe
        or not getattr(user, "is_receive_wechat_message", True)
        or not user.wx_openid
    ):
        return False

    last_read_id = (
        ConversationReadState.objects.filter(
            conversation=message.conversation,
            user=user,
        )
        .values_list("last_read_message_id", flat=True)
        .first()
    )
    if last_read_id and last_read_id >= message.id:
        return False

    if SendMessageLog.objects.filter(
        scene=SendMessageLog.Scene.CHAT_UNREAD,
        channel=SendMessageLog.Channel.WECHAT,
        is_success=True,
        payload__message_id=message.id,
    ).exists():
        return False

    if not _acquire_debounce_lock(
        conversation_id=message.conversation_id,
        user_id=user.id,
        ttl_seconds=delay_seconds,
    ):
        return False

    ok, error = _send_wechat_text(user.wx_openid, _UNREAD_CONTENT)
    SendMessageLog.objects.create(
        patient=patient,
        user=user,
        openid=user.wx_openid or "",
        channel=SendMessageLog.Channel.WECHAT,
        scene=SendMessageLog.Scene.CHAT_UNREAD,
        biz_date=timezone.localdate(message.created_at) if message.created_at else None,
        content=_UNREAD_CONTENT,
        payload={
            "message_id": message.id,
            "conversation_id": message.conversation_id,
            "sender_role": int(message.sender_role_snapshot or 0),
            "message_created_at": message.created_at.isoformat() if message.created_at else None,
        },
        is_success=ok,
        error_message=error or "",
    )
    if not ok:
        _release_debounce_lock(
            conversation_id=message.conversation_id,
            user_id=user.id,
        )
    return ok


def send_chat_unread_notifications(
    *,
    as_of: datetime | None = None,
    delay_seconds: int = _DEFAULT_DELAY_SECONDS,
    limit: int = _DEFAULT_LIMIT,
) -> int:
    """
    扫描未读消息并推送公众号提醒。

    规则：
    - 仅患者会话（PATIENT_STUDIO）。
    - 仅医生端消息（排除患者/家属发送）。
    - 消息创建超过 delay_seconds 且仍未读。
    - 同一消息仅成功推送一次（基于 SendMessageLog 去重）。
    """
    if as_of is None:
        as_of = timezone.now()
    delay_seconds = max(0, int(delay_seconds))
    cutoff = as_of - timedelta(seconds=delay_seconds)

    messages = list(
        Message.objects.filter(
            conversation__type=ConversationType.PATIENT_STUDIO,
            created_at__lte=cutoff,
        )
        .exclude(
            sender_role_snapshot__in=[
                MessageSenderRole.PATIENT,
                MessageSenderRole.FAMILY,
            ]
        )
        .select_related("conversation__patient__user")
        .order_by("id")[: max(1, min(limit, 500))]
    )
    if not messages:
        return 0

    existing_ids = _load_sent_message_ids(messages)
    read_state_map = _load_read_state_map(messages)

    logs: List[SendMessageLog] = []
    success_count = 0
    for message in messages:
        if message.id in existing_ids:
            continue
        conversation = message.conversation
        if not conversation:
            continue
        patient = conversation.patient
        user = patient.user if patient else None
        if (
            not user
            or not user.is_active
            or not user.is_subscribe
            or not getattr(user, "is_receive_wechat_message", True)
            or not user.wx_openid
        ):
            continue

        last_read_id = read_state_map.get((conversation.id, user.id))
        if last_read_id and last_read_id >= message.id:
            continue

        if not _acquire_debounce_lock(
            conversation_id=conversation.id,
            user_id=user.id,
            ttl_seconds=delay_seconds,
        ):
            continue

        content = _UNREAD_CONTENT
        ok, error = _send_wechat_text(user.wx_openid, content)
        payload = {
            "message_id": message.id,
            "conversation_id": conversation.id,
            "sender_role": int(message.sender_role_snapshot or 0),
            "message_created_at": message.created_at.isoformat(),
        }
        logs.append(
            SendMessageLog(
                patient=patient,
                user=user,
                openid=user.wx_openid or "",
                channel=SendMessageLog.Channel.WECHAT,
                scene=SendMessageLog.Scene.CHAT_UNREAD,
                biz_date=message.created_at.date() if message.created_at else None,
                content=content,
                payload=payload,
                is_success=ok,
                error_message=error or "",
            )
        )
        if not ok:
            _release_debounce_lock(
                conversation_id=conversation.id,
                user_id=user.id,
            )
        if ok:
            success_count += 1

    if logs:
        SendMessageLog.objects.bulk_create(logs, batch_size=200)

    return success_count


def _load_sent_message_ids(messages: Iterable[Message]) -> Set[int]:
    message_ids = [msg.id for msg in messages]
    if not message_ids:
        return set()
    existing = SendMessageLog.objects.filter(
        scene=SendMessageLog.Scene.CHAT_UNREAD,
        channel=SendMessageLog.Channel.WECHAT,
        is_success=True,
        payload__message_id__in=message_ids,
    ).values_list("payload__message_id", flat=True)
    return {int(value) for value in existing if value is not None}


def _load_read_state_map(messages: Iterable[Message]) -> Dict[Tuple[int, int], int | None]:
    conversation_ids: Set[int] = set()
    user_ids: Set[int] = set()
    for msg in messages:
        if msg.conversation_id:
            conversation_ids.add(msg.conversation_id)
        patient_user_id = msg.conversation.patient.user_id if msg.conversation and msg.conversation.patient else None
        if patient_user_id:
            user_ids.add(patient_user_id)

    if not conversation_ids or not user_ids:
        return {}

    state_rows = ConversationReadState.objects.filter(
        conversation_id__in=conversation_ids,
        user_id__in=user_ids,
    ).values("conversation_id", "user_id", "last_read_message_id")

    return {
        (row["conversation_id"], row["user_id"]): row["last_read_message_id"]
        for row in state_rows
    }


def _send_wechat_text(openid: str, content: str) -> tuple[bool, str | None]:
    """
    发送公众号文本消息。
    如需替换为模板消息，可在此处统一调整。
    """
    if not openid:
        return False, "缺少 openid"
    try:
        from wx.services.client import wechat_client

        wechat_client.message.send_text(openid, content)
        return True, None
    except Exception as exc:  # pragma: no cover - 网络/配置异常
        return False, str(exc)


def _acquire_debounce_lock(
    *,
    conversation_id: int,
    user_id: int,
    ttl_seconds: int,
) -> bool:
    if not conversation_id or not user_id or ttl_seconds <= 0:
        return True
    key = f"chat_unread:{conversation_id}:{user_id}"
    try:
        redis_conn = get_redis_connection("default")
        return bool(redis_conn.set(key, "1", nx=True, ex=ttl_seconds))
    except Exception:  # pragma: no cover - Redis 不可用时不阻断发送
        return True


def _release_debounce_lock(*, conversation_id: int, user_id: int) -> None:
    if not conversation_id or not user_id:
        return
    key = f"chat_unread:{conversation_id}:{user_id}"
    try:
        redis_conn = get_redis_connection("default")
        redis_conn.delete(key)
    except Exception:  # pragma: no cover - Redis 不可用时忽略
        return
