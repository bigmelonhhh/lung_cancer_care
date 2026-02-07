import json
import logging
from django.http import JsonResponse, HttpRequest
from django.views.decorators.http import require_GET, require_POST
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from chat.services.chat import ChatService
from chat.models import Conversation, MessageSenderRole
from users.models import PatientRelation
from users.decorators import check_doctor_or_assistant
from users.models.patient_profile import PatientProfile


def _format_datetime_for_display(dt) -> str:
    if not dt:
        return ""
    try:
        local_dt = timezone.localtime(dt)
    except Exception:
        local_dt = dt
    return local_dt.strftime("%Y-%m-%d %H:%M")


def _normalize_family_sender_name(msg) -> str:
    try:
        if msg.sender_role_snapshot == MessageSenderRole.FAMILY:
            relation = PatientRelation.objects.filter(
                patient=getattr(msg.conversation, "patient", None),
                user=msg.sender,
                is_active=True,
            ).first()
            name = ""
            label = "家属"
            if relation:
                name = relation.name or ""
                label = relation.relation_name or relation.get_relation_type_display() or "家属"
            if not name:
                name = getattr(msg.sender, "display_name", "") or msg.sender_display_name_snapshot or ""
            return f"{name}({label})"
    except Exception:
        pass
    return msg.sender_display_name_snapshot

def _serialize_message(msg) -> dict:
    created_at_iso = msg.created_at.isoformat() if getattr(msg, "created_at", None) else ""
    return {
        "id": msg.id,
        "sender_id": msg.sender_id,
        "sender_role": msg.sender_role_snapshot,
        "sender_name": _normalize_family_sender_name(msg),
        "studio_name": msg.studio_name_snapshot,
        "content_type": msg.content_type,
        "text_content": msg.text_content,
        "image_url": msg.image.url if msg.image else "",
        "created_at": created_at_iso,
        "created_at_display": _format_datetime_for_display(getattr(msg, "created_at", None)),
    }


def _can_view_conversation(user, conversation: Conversation, service: ChatService) -> bool:
    if conversation is None or user is None:
        return False

    if service._is_user_studio_member(user, conversation.studio):
        return True

    patient = getattr(conversation, "patient", None)
    patient_doctor = getattr(patient, "doctor", None) if patient else None
    patient_studio = getattr(patient_doctor, "studio", None) if patient_doctor else None

    if not patient_studio:
        return False

    if service._is_user_studio_member(user, patient_studio):
        return True

    return False


def _log_permission_denied(request: HttpRequest, conversation: Conversation, reason: str) -> None:
    user = getattr(request, "user", None)
    doctor_profile = getattr(user, "doctor_profile", None)
    assistant_profile = getattr(user, "assistant_profile", None)
    patient = getattr(conversation, "patient", None)
    patient_doctor = getattr(patient, "doctor", None) if patient else None
    patient_studio = getattr(patient_doctor, "studio", None) if patient_doctor else None

    


@require_GET
@login_required
@check_doctor_or_assistant
def get_chat_context(request: HttpRequest):
    """获取聊天上下文信息（当前用户信息、角色、会话标签、权限等）"""
    user = request.user
    doctor_profile = getattr(user, "doctor_profile", None)
    assistant_profile = getattr(user, "assistant_profile", None)
    
    if doctor_profile:
        # 1. 获取真实姓名
        real_name = doctor_profile.name
        
        # 2. 获取角色和工作室信息
        studio = doctor_profile.studio
        role_label = "医生"
        is_director = False
        
        if studio:
            if studio.owner_doctor == doctor_profile:
                role_label = "主任"
                is_director = True
            else:
                role_label = "平台医生"
    elif assistant_profile:
        # 助理逻辑
        real_name = assistant_profile.name
        role_label = "平台助理"
        # 尝试获取关联的第一个医生的工作室作为默认上下文
        first_doc = assistant_profile.doctors.first()
        studio = first_doc.studio if first_doc else None
        is_director = False
    else:
         return JsonResponse({'status': 'error', 'message': 'Not a doctor or assistant account'}, status=400)

    # 3. 计算会话信息
    chat_service = ChatService()
    patient_id = request.GET.get('patient_id')
    
    patient_conv_id = None
    internal_conv_id = None
    tab_patient_label = "患者"
    tab_internal_label = "内部会话"
    can_send_patient = True
    can_send_internal = True
    internal_unread_count = 0
    
    if patient_id:
        try:
            patient = PatientProfile.objects.get(id=patient_id)
            tab_patient_label = f"{patient.name}(患者)"
            
            # 确定当前操作的工作室
            target_studio = None
            if patient.doctor and patient.doctor.studio:
                target_studio = patient.doctor.studio
            else:
                target_studio = studio
                
            if target_studio:
                # 获取/创建会话
                try:
                    p_conv = chat_service.get_or_create_patient_conversation(patient, target_studio, user)
                    patient_conv_id = p_conv.id
                    
                    i_conv = chat_service.get_or_create_internal_conversation(patient, target_studio, user)
                    internal_conv_id = i_conv.id
                    
                    # 获取内部会话未读数 (仅当当前用户是主任时才有意义，但通用逻辑也无妨)
                    internal_unread_count = chat_service.get_unread_count(i_conv, user)
                    
                except Exception as e:
                    logging.info(f"Error creating conversation: {e}")

                if is_director:
                    # 主任视角
                    can_send_patient = False # 主任对患者会话只读
                    can_send_internal = True
                    
                    # 内部会话对方标签：显示关联的平台医生/助理
                    # 优先显示正在处理该患者的非主任医生或助理
                    # 简化逻辑：显示“平台医生”或具体助理名
                    # 如果有 assistants，取第一个
                    assistant = doctor_profile.assistants.first()
                    if assistant:
                        tab_internal_label = f"{assistant.name}(平台医生)"
                    else:
                        tab_internal_label = "平台医生(平台医生)"
                else:
                    # 平台医生/助理视角
                    can_send_patient = True
                    can_send_internal = True
                    
                    # 内部会话对方标签：显示主任
                    if target_studio.owner_doctor:
                        owner = target_studio.owner_doctor
                        title = owner.title or ""
                        hospital = owner.hospital or ""
                        tab_internal_label = f"{owner.name}({hospital} {title})".strip()
                    else:
                        tab_internal_label = "主任(未知)"
                        
        except PatientProfile.DoesNotExist:
            pass
    
    return JsonResponse({
        'status': 'success',
        'data': {
            'user_name': real_name,
            'role_label': role_label,
            'is_director': is_director,
            'studio_name': studio.name if studio else '',
            # New fields
            'tab_patient_label': tab_patient_label,
            'tab_internal_label': tab_internal_label,
            'patient_conversation_id': patient_conv_id,
            'internal_conversation_id': internal_conv_id,
            'can_send_patient': can_send_patient,
            'can_send_internal': can_send_internal,
            'internal_unread_count': internal_unread_count
        }
    })

@require_GET
@login_required
@check_doctor_or_assistant
def list_conversations(request: HttpRequest):
    """获取会话列表"""
    service = ChatService()
    user = request.user
    doctor_profile = getattr(user, "doctor_profile", None)
    assistant_profile = getattr(user, "assistant_profile", None)
    
    studios = set()
    if doctor_profile and doctor_profile.studio:
        studios.add(doctor_profile.studio)
    if assistant_profile:
        for doc in assistant_profile.doctors.all():
            if doc.studio:
                studios.add(doc.studio)
                
    all_summaries = []
    for studio in studios:
        summaries = service.list_patient_conversation_summaries(studio, user)
        all_summaries.extend(summaries)

    for summary in all_summaries:
        last_message_at = summary.get("last_message_at")
        summary["last_message_at_display"] = _format_datetime_for_display(last_message_at)
        
    # Sort by last message time descending
    all_summaries.sort(key=lambda x: str(x.get('last_message_at') or ''), reverse=True)
    
    return JsonResponse({'status': 'success', 'conversations': all_summaries})

@require_GET
@login_required
@check_doctor_or_assistant
def list_messages(request: HttpRequest):
    """获取会话消息列表"""
    conversation_id = request.GET.get('conversation_id')
    if not conversation_id:
        return JsonResponse({'status': 'error', 'message': 'conversation_id is required'}, status=400)
        
    service = ChatService()
    try:
        conversation = (
            Conversation.objects.select_related("patient", "patient__doctor", "patient__doctor__studio", "studio")
            .get(pk=conversation_id)
        )

        if not _can_view_conversation(request.user, conversation, service):
            _log_permission_denied(request, conversation, "list_messages")
            return JsonResponse(
                {"status": "error", "message": "Permission denied", "code": "permission_denied"},
                status=403,
            )

        after_id = request.GET.get('after_id')
        if after_id:
            try:
                after_id = int(after_id)
            except ValueError:
                after_id = None
            
        messages = service.list_conversation_messages(conversation, after_id=after_id)
        
        data = [_serialize_message(msg) for msg in messages]
            
        return JsonResponse({'status': 'success', 'messages': data})
    except Conversation.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Conversation not found'}, status=404)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@require_POST
@login_required
@check_doctor_or_assistant
def send_text_message(request: HttpRequest):
    """发送文本消息"""
    service = ChatService()
    try:
        data = json.loads(request.body)
        conversation_id = data.get('conversation_id')
        content = data.get('content')
        
        if not conversation_id:
            return JsonResponse({'status': 'error', 'message': 'conversation_id is required'}, status=400)
            
        conversation = Conversation.objects.get(pk=conversation_id)
        message = service.create_text_message(conversation, request.user, content)
        
        return JsonResponse({
            'status': 'success',
            'message': {
                'id': message.id,
                'created_at': message.created_at.isoformat(),
                'created_at_display': _format_datetime_for_display(message.created_at),
            }
        })
    except Conversation.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Conversation not found'}, status=404)
    except ValidationError as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@require_POST
@login_required
@check_doctor_or_assistant
def upload_image_message(request: HttpRequest):
    """发送图片消息"""
    service = ChatService()
    try:
        conversation_id = request.POST.get('conversation_id')
        image_file = request.FILES.get('image')
        
        if not conversation_id:
            return JsonResponse({'status': 'error', 'message': 'conversation_id is required'}, status=400)
            
        conversation = Conversation.objects.get(pk=conversation_id)
        message = service.create_image_message(conversation, request.user, image_file)
        
        return JsonResponse({
            'status': 'success',
            'message': {
                'id': message.id,
                'created_at': message.created_at.isoformat(),
                'created_at_display': _format_datetime_for_display(message.created_at),
                'image_url': message.image.url
            }
        })
    except Conversation.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Conversation not found'}, status=404)
    except ValidationError as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@require_POST
@login_required
@check_doctor_or_assistant
def forward_message(request: HttpRequest):
    """转发消息给主任"""
    service = ChatService()
    try:
        data = json.loads(request.body)
        patient_conversation_id = data.get('patient_conversation_id')
        message_id = data.get('message_id')
        note = data.get('note')
        
        if not patient_conversation_id or not message_id:
            return JsonResponse({'status': 'error', 'message': 'patient_conversation_id and message_id are required'}, status=400)
            
        patient_conversation = Conversation.objects.get(pk=patient_conversation_id)
        message = service.forward_to_director(patient_conversation, message_id, request.user, note)
        
        return JsonResponse({
            'status': 'success',
            'message': {
                'id': message.id,
                'created_at': message.created_at.isoformat(),
                'created_at_display': _format_datetime_for_display(message.created_at),
            }
        })
    except Conversation.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Conversation not found'}, status=404)
    except ValidationError as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@require_POST
@login_required
@check_doctor_or_assistant
def mark_read(request: HttpRequest):
    """标记已读"""
    service = ChatService()
    try:
        data = json.loads(request.body)
        conversation_id = data.get('conversation_id')
        last_message_id = data.get('last_message_id')
        
        if not conversation_id:
            return JsonResponse({'status': 'error', 'message': 'conversation_id is required'}, status=400)
            
        conversation = Conversation.objects.get(pk=conversation_id)
        service.mark_conversation_read(conversation, request.user, last_message_id)
        
        return JsonResponse({'status': 'success'})
    except Conversation.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Conversation not found'}, status=404)
    except ValidationError as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@require_GET
@login_required
@check_doctor_or_assistant
def get_unread_count(request: HttpRequest):
    """获取指定会话的未读数量"""
    conversation_id = request.GET.get('conversation_id')
    if not conversation_id:
        return JsonResponse({'status': 'error', 'message': 'conversation_id is required'}, status=400)
        
    service = ChatService()
    try:
        conversation = (
            Conversation.objects.select_related("patient", "patient__doctor", "patient__doctor__studio", "studio")
            .get(pk=conversation_id)
        )
        if not _can_view_conversation(request.user, conversation, service):
            _log_permission_denied(request, conversation, "get_unread_count")
            return JsonResponse(
                {"status": "error", "message": "Permission denied", "code": "permission_denied"},
                status=403,
            )
             
        count = service.get_unread_count(conversation, request.user)
        return JsonResponse({'status': 'success', 'unread_count': count})
    except Conversation.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Conversation not found'}, status=404)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
