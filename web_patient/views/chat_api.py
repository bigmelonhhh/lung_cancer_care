import json
from django.http import JsonResponse, HttpRequest
from django.views.decorators.http import require_GET, require_POST
from django.core.exceptions import ValidationError
from django.utils import timezone
from chat.services.chat import ChatService
from chat.models import MessageContentType
from users.decorators import check_patient, auto_wechat_login
from web_patient.views.chat import get_patient_chat_title
from users.models import CustomUser
from users.models import PatientProfile


def _format_datetime_for_display(dt) -> str:
    if not dt:
        return ""
    try:
        local_dt = timezone.localtime(dt)
    except Exception:
        local_dt = dt
    return local_dt.strftime("%Y-%m-%d %H:%M")

@require_GET
@auto_wechat_login
@check_patient
def list_messages(request: HttpRequest):
    """获取消息列表"""
    patient = request.patient
    service = ChatService() 
    
    try:
        conversation = service.get_or_create_patient_conversation(patient=patient)
        
        after_id = request.GET.get('after_id')
        if after_id:
            try:
                after_id = int(after_id)
            except ValueError:
                after_id = None
            
        messages = service.list_conversation_messages(conversation, after_id=after_id)
        
        data = []
        for msg in messages:
            content_type_str = 'text'
            if msg.content_type == MessageContentType.IMAGE:
                content_type_str = 'image'
            
            data.append({
                'id': msg.id,
                'sender_id': msg.sender_id,
                'sender_role': msg.sender_role_snapshot,
                # 修复：患者端应显示真实发送者名称（本人/家属/医生等），而非工作室名称
                'sender_name': msg.sender_display_name_snapshot,
                'studio_name': msg.studio_name_snapshot,
                # 新增：标记患者侧（本人/家属）用于前端正确判断左右气泡
                'is_patient_side': msg.sender_role_snapshot in (1, 2),
                'content_type': content_type_str,
                'text_content': msg.text_content or "",
                'image_url': msg.image.url if msg.image else '',
                'created_at': msg.created_at.isoformat(),
                'created_at_display': _format_datetime_for_display(msg.created_at),
            })
            
        return JsonResponse({'status': 'success', 'messages': data})
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
