import json
from django.http import JsonResponse, HttpRequest
from django.views.decorators.http import require_GET, require_POST
from django.core.exceptions import ValidationError
from chat.services.chat import ChatService
from chat.models import MessageContentType
from users.decorators import check_patient, auto_wechat_login

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
                'sender_name': msg.sender_display_name_snapshot,
                'studio_name': msg.studio_name_snapshot,
                'content_type': content_type_str,
                'text_content': msg.text_content or "",
                'image_url': msg.image.url if msg.image else '',
                'created_at': msg.created_at.isoformat(),
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
        
        conversation = service.get_or_create_patient_conversation(patient=patient)
        message = service.create_text_message(conversation, request.user, content)
        
        return JsonResponse({
            'status': 'success',
            'message': {
                'id': message.id,
                'created_at': message.created_at.isoformat()
            }
        })
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
        
        conversation = service.get_or_create_patient_conversation(patient=patient)
        message = service.create_image_message(conversation, request.user, image_file)
        
        return JsonResponse({
            'status': 'success',
            'message': {
                'id': message.id,
                'created_at': message.created_at.isoformat(),
                'image_url': message.image.url
            }
        })
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
