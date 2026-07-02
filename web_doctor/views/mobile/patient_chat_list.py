import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.cache import never_cache

from chat.models import ConversationReadState, Message
from chat.models.choices import ConversationType
from chat.services.chat import ChatService
from users import choices
from users.decorators import check_doctor_or_assistant
from users.models import PatientProfile
from web_doctor.views.chat_api import (
    _assistant_can_send_patient_messages,
    _can_view_conversation,
    _serialize_message,
)
from web_doctor.views.workspace import _get_workspace_patients


PAGE_SIZE = 20


def _resolve_target_studio(request: HttpRequest, patient) -> object | None:
    target_studio = getattr(getattr(patient, "doctor", None), "studio", None)
    if target_studio is not None:
        return target_studio

    doctor_profile = getattr(request.user, "doctor_profile", None)
    if doctor_profile is not None:
        if doctor_profile.studio is not None:
            return doctor_profile.studio
        owned_studio = doctor_profile.owned_studios.first()
        if owned_studio is not None:
            return owned_studio

    assistant_profile = getattr(request.user, "assistant_profile", None)
    if assistant_profile is not None:
        first_doctor = (
            assistant_profile.doctors.select_related("studio")
            .prefetch_related("owned_studios")
            .first()
        )
        if first_doctor is not None:
            if first_doctor.studio is not None:
                return first_doctor.studio
            owned_studio = first_doctor.owned_studios.first()
            if owned_studio is not None:
                return owned_studio

    return None


def _resolve_accessible_patient(request: HttpRequest, patient_id: int):
    patients_qs = _get_workspace_patients(request.user, query=None).select_related(
        "doctor",
        "doctor__studio",
        "user",
    )
    patient = patients_qs.filter(pk=patient_id).first()
    if patient is not None:
        return patient

    doctor_profile = getattr(request.user, "doctor_profile", None)
    if doctor_profile is None:
        return None

    candidate = (
        PatientProfile.objects.select_related("doctor", "doctor__studio", "user")
        .filter(pk=patient_id, is_active=True)
        .first()
    )
    if candidate is None:
        return None
    candidate_studio = getattr(getattr(candidate, "doctor", None), "studio", None)
    if candidate_studio is None:
        return None
    if candidate_studio.owner_doctor_id != doctor_profile.id:
        return None
    return candidate


def _is_director_for_studio(user, studio) -> bool:
    doctor_profile = getattr(user, "doctor_profile", None)
    if doctor_profile is None or studio is None:
        return False
    return studio.owner_doctor_id == doctor_profile.id


def _load_message_page(request: HttpRequest, conversation) -> tuple[list[dict], bool, str]:
    cursor = request.GET.get("cursor")
    before_id = None
    if cursor:
        try:
            before_id = int(cursor)
        except (TypeError, ValueError):
            before_id = None

    base_qs = Message.objects.filter(conversation=conversation)
    if before_id:
        base_qs = base_qs.filter(id__lt=before_id)

    page_qs = base_qs.order_by("-id")[:PAGE_SIZE]
    messages = list(reversed(list(page_qs)))

    last_read_id = (
        ConversationReadState.objects.filter(conversation=conversation, user=request.user)
        .values_list("last_read_message_id", flat=True)
        .first()
    )
    last_read_id = int(last_read_id or 0)

    data: list[dict] = []
    for msg in messages:
        serialized = _serialize_message(msg)
        serialized["is_unread"] = (msg.sender_id != request.user.id) and (msg.id > last_read_id)
        data.append(serialized)

    has_next = False
    next_cursor = ""
    if messages:
        earliest_id = messages[0].id
        has_next = Message.objects.filter(conversation=conversation, id__lt=earliest_id).exists()
        next_cursor = str(earliest_id) if has_next else ""

    return data, has_next, next_cursor


def _build_chat_api_urls() -> dict[str, str]:
    return {
        "list": reverse("web_doctor:chat_api_list_messages"),
        "send": reverse("web_doctor:chat_api_send_text"),
        "upload": reverse("web_doctor:chat_api_upload_image"),
        "read": reverse("web_doctor:chat_api_mark_read"),
    }


def _build_base_chat_context(
    *,
    patient,
    data: list[dict],
    has_next: bool,
    next_cursor: str,
    conversation_id: int,
    can_chat: bool,
) -> dict:
    return {
        "patient": patient,
        "messages": json.dumps(data, ensure_ascii=False),
        "has_next": has_next,
        "next_cursor": next_cursor,
        "conversation_id": conversation_id,
        "can_chat": can_chat,
        "chat_api_urls": _build_chat_api_urls(),
    }


@login_required
@check_doctor_or_assistant
@never_cache
def patient_chat_list(request: HttpRequest, patient_id: int) -> HttpResponse:
    patient = _resolve_accessible_patient(request, patient_id)
    if patient is None:
        raise Http404("未找到患者")

    service = ChatService()
    target_studio = _resolve_target_studio(request, patient)
    if target_studio is None:
        raise Http404("未找到患者工作室")

    conversation = service.get_or_create_patient_conversation(
        patient=patient,
        studio=target_studio,
        operator=request.user,
    )
    if not _can_view_conversation(request.user, conversation, service):
        return JsonResponse(
            {"status": "error", "message": "Permission denied", "code": "permission_denied"},
            status=403,
        )

    data, has_next, next_cursor = _load_message_page(request, conversation)

    wants_json = request.GET.get("format") == "json" or request.headers.get("x-requested-with") == "XMLHttpRequest"
    if wants_json:
        return JsonResponse(
            {
                "messages": data,
                "has_next": has_next,
                "next_cursor": next_cursor,
            }
        )

    is_assistant = request.user.user_type == choices.UserType.ASSISTANT
    is_director = _is_director_for_studio(request.user, target_studio)
    show_internal_chat_fab = is_assistant or is_director
    internal_chat_fab_label = ""
    if is_assistant:
        internal_chat_fab_label = "联系主任"
    elif is_director:
        internal_chat_fab_label = "联系助理"

    context = _build_base_chat_context(
        patient=patient,
        data=data,
        has_next=has_next,
        next_cursor=next_cursor,
        conversation_id=conversation.id,
        can_chat=is_assistant and _assistant_can_send_patient_messages(request.user),
    )
    context.update(
        {
            "show_internal_chat_fab": show_internal_chat_fab,
            "internal_chat_url": reverse(
                "web_doctor:mobile_patient_internal_chat",
                kwargs={"patient_id": patient.id},
            ),
            "internal_chat_fab_label": internal_chat_fab_label,
        }
    )

    return render(request, "web_doctor/mobile/patient_chat_list.html", context)


@login_required
@check_doctor_or_assistant
@never_cache
def patient_internal_chat(request: HttpRequest, patient_id: int) -> HttpResponse:
    patient = _resolve_accessible_patient(request, patient_id)
    if patient is None:
        raise Http404("未找到患者")

    target_studio = _resolve_target_studio(request, patient)
    if target_studio is None:
        raise Http404("未找到患者工作室")

    is_assistant = request.user.user_type == choices.UserType.ASSISTANT
    is_director = _is_director_for_studio(request.user, target_studio)
    if not (is_assistant or is_director):
        raise PermissionDenied("仅主任医生或医生助理可访问内部聊天。")

    service = ChatService()
    conversation = service.get_or_create_internal_conversation(
        patient=patient,
        studio=target_studio,
        operator=request.user,
    )
    if not _can_view_conversation(request.user, conversation, service):
        return JsonResponse(
            {"status": "error", "message": "Permission denied", "code": "permission_denied"},
            status=403,
        )

    data, has_next, next_cursor = _load_message_page(request, conversation)

    wants_json = request.GET.get("format") == "json" or request.headers.get("x-requested-with") == "XMLHttpRequest"
    if wants_json:
        return JsonResponse(
            {
                "messages": data,
                "has_next": has_next,
                "next_cursor": next_cursor,
            }
        )

    counterpart_label = "医生助理"
    if is_assistant:
        owner = getattr(target_studio, "owner_doctor", None)
        counterpart_label = (getattr(owner, "name", "") or "主任医生").strip()

    context = _build_base_chat_context(
        patient=patient,
        data=data,
        has_next=has_next,
        next_cursor=next_cursor,
        conversation_id=conversation.id,
        can_chat=True,
    )
    context.update(
        {
            "counterpart_label": counterpart_label,
            "conversation_type": ConversationType.INTERNAL,
            "back_url": reverse(
                "web_doctor:mobile_patient_chat_list",
                kwargs={"patient_id": patient.id},
            ),
        }
    )
    return render(request, "web_doctor/mobile/patient_internal_chat.html", context)
