import json
from django.http import JsonResponse, HttpRequest
from django.views.decorators.http import require_GET, require_POST
from django.core.exceptions import ValidationError
from django.utils import timezone
from chat.services.chat import ChatService
from chat.models import Message, MessageContentType, MessageSenderRole
from users.decorators import check_patient, auto_wechat_login
from web_patient.views.chat import get_patient_chat_title
from users.models import CustomUser
from users.models import PatientProfile

PAGE_SIZE = 50


def _format_datetime_for_display(dt) -> str:
    if not dt:
        return ""
    try:
        local_dt = timezone.localtime(dt)
    except Exception:
        local_dt = dt
    return local_dt.strftime("%Y-%m-%d %H:%M")


def _parse_int(value):
    if not value:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _serialize_patient_message(msg) -> dict:
    role = msg.sender_role_snapshot
    if role in (MessageSenderRole.PATIENT, MessageSenderRole.FAMILY):
        sender_name = msg.sender_display_name_snapshot
    else:
        sender_name = msg.studio_name_snapshot or msg.sender_display_name_snapshot

    content_type_str = 'text'
    if msg.content_type == MessageContentType.IMAGE:
        content_type_str = 'image'

    return {
        'id': msg.id,
        'sender_id': msg.sender_id,
        'sender_role': msg.sender_role_snapshot,
        # 患者/家属显示真实姓名，医护侧显示工作室名称
        'sender_name': sender_name,
        'studio_name': msg.studio_name_snapshot,
        # 标记患者侧（本人/家属）用于前端正确判断左右气泡
        'is_patient_side': msg.sender_role_snapshot in (1, 2),
        'content_type': content_type_str,
        'text_content': msg.text_content or "",
        'image_url': msg.image.url if msg.image else '',
        'created_at': msg.created_at.isoformat(),
        'created_at_display': _format_datetime_for_display(msg.created_at),
    }


def _load_patient_message_page(conversation, *, after_id=None, before_id=None):
    qs = Message.objects.filter(conversation=conversation)

    if after_id:
        messages = list(qs.filter(id__gt=after_id).order_by("id")[:PAGE_SIZE])
        return messages, False, ""

    if before_id:
        page = list(qs.filter(id__lt=before_id).order_by("-id")[:PAGE_SIZE])
    else:
        page = list(qs.order_by("-id")[:PAGE_SIZE])

    messages = list(reversed(page))
    if not messages:
        return messages, False, ""

    earliest_id = messages[0].id
    has_next = qs.filter(id__lt=earliest_id).exists()
    next_cursor = str(earliest_id) if has_next else ""
    return messages, has_next, next_cursor

@require_GET
@auto_wechat_login
@check_patient
def list_messages(request: HttpRequest):
    """获取消息列表"""
    patient = request.patient
    service = ChatService() 

    try:
        conversation = service.get_or_create_patient_conversation(patient=patient)

        after_id = _parse_int(request.GET.get('after_id'))
        before_id = _parse_int(request.GET.get('before_id'))
        messages, has_next, next_cursor = _load_patient_message_page(
            conversation,
            after_id=after_id,
            before_id=before_id,
        )

        data = [_serialize_patient_message(msg) for msg in messages]
        return JsonResponse({
            'status': 'success',
            'messages': data,
            'has_next': has_next,
            'next_cursor': next_cursor,
        })
    except ValidationError as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@require_POST
@auto_wechat_login
@check_patient
def send_text_message(request: HttpRequest):
    """发送文本消息"""
    patient = request.patient
    service = ChatService()
    
    try:
        data = json.loads(request.body)
        content = data.get('content')
        role = data.get('role')
        
        conversation = service.get_or_create_patient_conversation(patient=patient)
        message = service.create_text_message(conversation, request.user, content)
        
        resp = {
            'status': 'success',
            'message': {
                'id': message.id,
                'created_at': message.created_at.isoformat(),
                'created_at_display': _format_datetime_for_display(message.created_at),
            }
        }
        if role:
            resp['role_echo'] = role
        return JsonResponse(resp)
    except ValidationError as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@require_POST
@auto_wechat_login
@check_patient
def upload_image_message(request: HttpRequest):
    """发送图片消息"""
    patient = request.patient
    service = ChatService()
    
    try:
        image_file = request.FILES.get('image')
        role = request.POST.get('role')
        
        conversation = service.get_or_create_patient_conversation(patient=patient)
        message = service.create_image_message(conversation, request.user, image_file)
        
        resp = {
            'status': 'success',
            'message': {
                'id': message.id,
                'created_at': message.created_at.isoformat(),
                'created_at_display': _format_datetime_for_display(message.created_at),
                'image_url': message.image.url
            }
        }
        if role:
            resp['role_echo'] = role
        return JsonResponse(resp)
    except ValidationError as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@require_POST
@auto_wechat_login
@check_patient
def mark_read(request: HttpRequest):
    """标记已读"""
    patient = request.patient
    service = ChatService()
    
    try:
        data = json.loads(request.body)
        last_message_id = data.get('last_message_id')
        
        conversation = service.get_or_create_patient_conversation(patient=patient)
        service.mark_conversation_read(conversation, request.user, last_message_id)
        
        return JsonResponse({'status': 'success'})
    except ValidationError as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

def get_unread_chat_count(patient: PatientProfile, user: CustomUser) -> int:
    service = ChatService()
    try:
        conversation = service.get_or_create_patient_conversation(patient=patient)
        return service.get_unread_count(conversation, user)
    except Exception:
        return 0

@require_GET
@auto_wechat_login
@check_patient
def unread_count(request: HttpRequest):
    patient = request.patient
    count = get_unread_chat_count(patient, request.user)
    return JsonResponse({'status': 'success', 'count': count})

@require_POST
@auto_wechat_login
@check_patient
def reset_unread(request: HttpRequest):
    patient = request.patient
    service = ChatService()
    try:
        conversation = service.get_or_create_patient_conversation(patient=patient)
        state = service.mark_conversation_read(conversation, request.user, None)
        return JsonResponse({'status': 'success'})
    except ValidationError as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
