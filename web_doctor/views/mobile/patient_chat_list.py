import json

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render

from chat.models import ConversationReadState, Message
from chat.services.chat import ChatService
from users.decorators import check_doctor_or_assistant
from web_doctor.views.chat_api import _can_view_conversation, _serialize_message
from web_doctor.views.workspace import _get_workspace_patients


PAGE_SIZE = 20


@login_required
@check_doctor_or_assistant
def patient_chat_list(request: HttpRequest, patient_id: int) -> HttpResponse:
    patients_qs = _get_workspace_patients(request.user, query=None).select_related(
        "doctor",
        "doctor__studio",
        "user",
    )
    patient = patients_qs.filter(pk=patient_id).first()
    if patient is None:
        raise Http404("未找到患者")

    service = ChatService()
    target_studio = getattr(getattr(patient, "doctor", None), "studio", None)
    if target_studio is None:
        doctor_profile = getattr(request.user, "doctor_profile", None)
        target_studio = getattr(doctor_profile, "studio", None)

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

    wants_json = request.GET.get("format") == "json" or request.headers.get("x-requested-with") == "XMLHttpRequest"
    if wants_json:
        return JsonResponse(
            {
                "messages": data,
                "has_next": has_next,
                "next_cursor": next_cursor,
            }
        )

    context = {
        "patient": patient,
        "messages": json.dumps(data, ensure_ascii=False),
        "has_next": has_next,
        "next_cursor": next_cursor,
    }
    return render(request, "web_doctor/mobile/patient_chat_list.html", context)

