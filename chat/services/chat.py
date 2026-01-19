from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Iterable, Optional

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Case, CharField, Count, Value, When
from django.db.models.functions import ExtractHour, TruncMonth
from django.utils import timezone

from chat.models import (
    Conversation,
    ConversationReadState,
    ConversationType,
    ConversationSession,
    Message,
    MessageContentType,
    MessageSenderRole,
    PatientStudioAssignment,
)
from users import choices as user_choices
from users.models import CustomUser, DoctorStudio, PatientProfile, PatientRelation


class ChatService:
    """聊天领域服务，负责会话与消息处理。"""

    SESSION_GAP = timedelta(minutes=30)

    def get_or_create_patient_conversation(
        self,
        patient: PatientProfile,
        studio: Optional[DoctorStudio] = None,
        operator: Optional[CustomUser] = None,
    ) -> Conversation:
        """
        【功能说明】
        - 获取或创建患者会话（PATIENT_STUDIO）。

        【使用方法】
        - chat_service.get_or_create_patient_conversation(patient, studio, operator)

        【参数说明】
        - patient: PatientProfile 实例。
        - studio: DoctorStudio | None，缺省时使用患者当前归属工作室。
        - operator: CustomUser | None，记录创建人。

        【返回值说明】
        - Conversation 实例。
        """
        if patient is None:
            raise ValidationError("患者档案不能为空。")

        if studio is None:
            from users.services import PatientService

            assignment = PatientService().get_active_studio_assignment(patient)
            if not assignment:
                raise ValidationError("患者当前无有效工作室归属。")
            studio = assignment.studio

        with transaction.atomic():
            conversation, created = Conversation.objects.get_or_create(
                patient=patient,
                type=ConversationType.PATIENT_STUDIO,
                defaults={"studio": studio, "created_by": operator},
            )
            if not created and conversation.studio_id != studio.id:
                conversation.studio = studio
                conversation.save(update_fields=["studio", "updated_at"])

        return conversation

    def get_or_create_internal_conversation(
        self,
        patient: PatientProfile,
        studio: DoctorStudio,
        operator: Optional[CustomUser] = None,
    ) -> Conversation:
        """
        【功能说明】
        - 获取或创建内部会话（INTERNAL），用于升级沟通。

        【使用方法】
        - chat_service.get_or_create_internal_conversation(patient, studio, operator)

        【参数说明】
        - patient: PatientProfile 实例。
        - studio: DoctorStudio 实例。
        - operator: CustomUser | None，记录创建人。

        【返回值说明】
        - Conversation 实例。
        """
        if patient is None:
            raise ValidationError("患者档案不能为空。")
        if studio is None:
            raise ValidationError("工作室不能为空。")

        with transaction.atomic():
            conversation, created = Conversation.objects.get_or_create(
                patient=patient,
                type=ConversationType.INTERNAL,
                defaults={"studio": studio, "created_by": operator},
            )
            if not created and conversation.studio_id != studio.id:
                conversation.studio = studio
                conversation.save(update_fields=["studio", "updated_at"])

        return conversation

    def list_conversation_messages(
        self,
        conversation: Conversation,
        after_id: Optional[int] = None,
        before_id: Optional[int] = None,
        limit: int = 50,
    ) -> list[Message]:
        """
        【功能说明】
        - 按游标增量读取会话消息。

        【使用方法】
        - chat_service.list_conversation_messages(conversation, after_id=100)

        【参数说明】
        - conversation: Conversation 实例。
        - after_id: int | None，返回 id 大于该值的消息。
        - before_id: int | None，返回 id 小于该值的消息。
        - limit: int，最大返回数量。

        【返回值说明】
        - List[Message]，按 id 升序。
        """
        if conversation is None:
            raise ValidationError("会话不能为空。")

        limit = max(1, min(limit, 200))
        qs = Message.objects.filter(conversation=conversation)
        if after_id:
            qs = qs.filter(id__gt=after_id)
        if before_id:
            qs = qs.filter(id__lt=before_id)
        return list(qs.order_by("id")[:limit])

    def create_text_message(
        self,
        conversation: Conversation,
        sender: CustomUser,
        content: str,
    ) -> Message:
        """
        【功能说明】
        - 创建文本消息，并生成发送者快照。

        【使用方法】
        - chat_service.create_text_message(conversation, sender, "hello")

        【参数说明】
        - conversation: Conversation 实例。
        - sender: CustomUser 实例。
        - content: str，消息内容。

        【返回值说明】
        - Message 实例。
        """
        content = (content or "").strip()
        if not content:
            raise ValidationError("消息内容不能为空。")

        self._assert_sender_can_send(conversation, sender)
        sender_role = self._get_sender_role_snapshot(conversation, sender)
        display_name = self._get_sender_display_name(conversation, sender, sender_role)
        studio_name = self._get_studio_name_snapshot(conversation)

        with transaction.atomic():
            message = Message.objects.create(
                conversation=conversation,
                sender=sender,
                sender_role_snapshot=sender_role,
                sender_display_name_snapshot=display_name,
                studio_name_snapshot=studio_name,
                content_type=MessageContentType.TEXT,
                text_content=content,
            )
            self._touch_last_message(conversation, message.created_at)
            self._record_session_for_message(conversation, message.created_at)
        return message

    def create_image_message(
        self,
        conversation: Conversation,
        sender: CustomUser,
        image_file,
    ) -> Message:
        """
        【功能说明】
        - 创建图片消息，校验类型并生成发送者快照。

        【使用方法】
        - chat_service.create_image_message(conversation, sender, image_file)

        【参数说明】
        - conversation: Conversation 实例。
        - sender: CustomUser 实例。
        - image_file: 上传的图片文件。

        【返回值说明】
        - Message 实例。
        """
        if image_file is None:
            raise ValidationError("图片不能为空。")

        content_type = getattr(image_file, "content_type", "")
        if content_type and not content_type.startswith("image/"):
            raise ValidationError("仅支持图片上传。")

        self._assert_sender_can_send(conversation, sender)
        sender_role = self._get_sender_role_snapshot(conversation, sender)
        display_name = self._get_sender_display_name(conversation, sender, sender_role)
        studio_name = self._get_studio_name_snapshot(conversation)

        with transaction.atomic():
            message = Message.objects.create(
                conversation=conversation,
                sender=sender,
                sender_role_snapshot=sender_role,
                sender_display_name_snapshot=display_name,
                studio_name_snapshot=studio_name,
                content_type=MessageContentType.IMAGE,
                image=image_file,
            )
            self._touch_last_message(conversation, message.created_at)
            self._record_session_for_message(conversation, message.created_at)
        return message

    def forward_to_director(
        self,
        patient_conversation: Conversation,
        source_message_id: int,
        operator: CustomUser,
        note: Optional[str] = None,
    ) -> Message:
        """
        【功能说明】
        - 将患者会话中的消息升级转发至内部会话。

        【使用方法】
        - chat_service.forward_to_director(patient_conv, message_id, operator, note)

        【参数说明】
        - patient_conversation: Conversation，类型必须为 PATIENT_STUDIO。
        - source_message_id: int，原消息 id。
        - operator: CustomUser，执行转发的操作人。
        - note: str | None，追加说明。

        【返回值说明】
        - Message 实例（内部会话中生成）。
        """
        if patient_conversation is None:
            raise ValidationError("患者会话不能为空。")
        if patient_conversation.type != ConversationType.PATIENT_STUDIO:
            raise ValidationError("仅支持从患者会话转发。")
        if operator is None:
            raise ValidationError("操作人不能为空。")
        if operator.user_type == user_choices.UserType.PATIENT:
            raise ValidationError("患者不可转发内部会话。")

        source_message = (
            Message.objects.filter(
                pk=source_message_id, conversation=patient_conversation
            ).first()
        )
        if not source_message:
            raise ValidationError("原消息不存在。")

        internal_conversation = self.get_or_create_internal_conversation(
            patient=patient_conversation.patient,
            studio=patient_conversation.studio,
            operator=operator,
        )

        note = (note or "").strip()

        if source_message.content_type == MessageContentType.TEXT:
            forward_content = source_message.text_content or ""
            if note:
                forward_content = f"{note}\n{forward_content}" if forward_content else note
            return self.create_text_message(
                internal_conversation, operator, forward_content
            )

        if source_message.content_type == MessageContentType.IMAGE:
            if note:
                self.create_text_message(internal_conversation, operator, note)
            return self._clone_image_message(
                internal_conversation, operator, source_message.image
            )

        raise ValidationError("不支持的消息类型。")

    def mark_conversation_read(
        self,
        conversation: Conversation,
        user: CustomUser,
        last_message_id: Optional[int] = None,
    ) -> ConversationReadState:
        """
        【功能说明】
        - 更新用户在会话内的已读水位。

        【使用方法】
        - chat_service.mark_conversation_read(conversation, user, last_message_id)

        【参数说明】
        - conversation: Conversation 实例。
        - user: CustomUser 实例。
        - last_message_id: int | None，指定已读的消息 id。

        【返回值说明】
        - ConversationReadState 实例。
        """
        if conversation is None:
            raise ValidationError("会话不能为空。")
        if user is None:
            raise ValidationError("用户不能为空。")

        message = None
        if last_message_id:
            message = Message.objects.filter(
                conversation=conversation, pk=last_message_id
            ).first()
            if message is None:
                raise ValidationError("会话内未找到指定消息。")
        else:
            message = (
                Message.objects.filter(conversation=conversation)
                .order_by("-id")
                .first()
            )

        state, _created = ConversationReadState.objects.get_or_create(
            conversation=conversation,
            user=user,
        )
        state.last_read_message = message
        state.save(update_fields=["last_read_message", "updated_at"])
        return state

    def get_unread_count(self, conversation: Conversation, user: CustomUser) -> int:
        """
        【功能说明】
        - 计算指定会话的未读消息数。

        【使用方法】
        - chat_service.get_unread_count(conversation, user)

        【参数说明】
        - conversation: Conversation 实例。
        - user: CustomUser 实例。

        【返回值说明】
        - int，未读数量。
        """
        if conversation is None or user is None:
            return 0

        last_read_id = (
            ConversationReadState.objects.filter(conversation=conversation, user=user)
            .values_list("last_read_message_id", flat=True)
            .first()
        )
        qs = Message.objects.filter(conversation=conversation).exclude(sender=user)
        if last_read_id:
            qs = qs.filter(id__gt=last_read_id)
        return qs.count()

    def get_unread_counts(
        self, user: CustomUser, conversation_ids: Iterable[int]
    ) -> dict[int, int]:
        """
        【功能说明】
        - 批量计算多个会话的未读数量。

        【使用方法】
        - chat_service.get_unread_counts(user, [1, 2, 3])

        【参数说明】
        - user: CustomUser 实例。
        - conversation_ids: Iterable[int] 会话 id 列表。

        【返回值说明】
        - Dict[int, int]，键为会话 id。
        """
        if user is None:
            return {}

        counts: dict[int, int] = {}
        for conversation_id in conversation_ids:
            conversation = Conversation.objects.filter(pk=conversation_id).first()
            if conversation is None:
                counts[conversation_id] = 0
                continue
            counts[conversation_id] = self.get_unread_count(conversation, user)
        return counts

    def list_patient_conversation_summaries(
        self, studio: DoctorStudio, viewer: CustomUser
    ) -> list[dict]:
        """
        【功能说明】
        - 获取工作室的患者会话摘要列表。

        【使用方法】
        - chat_service.list_patient_conversation_summaries(studio, viewer)

        【参数说明】
        - studio: DoctorStudio 实例。
        - viewer: CustomUser 实例。

        【返回值说明】
        - List[dict]，包含患者与最近消息摘要。
        """
        if studio is None:
            raise ValidationError("工作室不能为空。")

        conversations = (
            Conversation.objects.filter(
                studio=studio, type=ConversationType.PATIENT_STUDIO
            )
            .select_related("patient")
            .order_by("-last_message_at", "-id")
        )
        conversation_ids = [conversation.id for conversation in conversations]
        unread_counts = self.get_unread_counts(viewer, conversation_ids)

        summaries: list[dict] = []
        for conversation in conversations:
            last_message = (
                Message.objects.filter(conversation=conversation)
                .order_by("-id")
                .first()
            )
            summaries.append(
                {
                    "conversation_id": conversation.id,
                    "patient_id": conversation.patient_id,
                    "patient_name": conversation.patient.name,
                    "last_message_id": last_message.id if last_message else None,
                    "last_message_at": last_message.created_at if last_message else None,
                    "last_message_type": last_message.content_type
                    if last_message
                    else None,
                    "last_message_text": last_message.text_content if last_message else "",
                    "last_message_image": last_message.image.url
                    if last_message and last_message.image
                    else "",
                    "unread_count": unread_counts.get(conversation.id, 0),
                }
            )
        return summaries

    def transfer_patient_to_studio(
        self,
        patient: PatientProfile,
        target_studio: DoctorStudio,
        operator: CustomUser,
        reason: Optional[str] = None,
    ) -> PatientStudioAssignment:
        """
        【功能说明】
        - 原子化转移患者归属，并记录历史。

        【使用方法】
        - chat_service.transfer_patient_to_studio(patient, studio, operator, reason)

        【参数说明】
        - patient: PatientProfile 实例。
        - target_studio: DoctorStudio 实例。
        - operator: CustomUser 实例。
        - reason: str | None，转移说明。

        【返回值说明】
        - PatientStudioAssignment 实例。
        """
        if patient is None:
            raise ValidationError("患者档案不能为空。")
        if target_studio is None:
            raise ValidationError("目标工作室不能为空。")
        if operator is None:
            raise ValidationError("操作人不能为空。")

        now = timezone.now()
        note = (reason or "").strip()

        with transaction.atomic():
            current_assignment = (
                PatientStudioAssignment.objects.select_for_update()
                .filter(patient=patient, end_at__isnull=True)
                .first()
            )
            if current_assignment and current_assignment.studio_id == target_studio.id:
                return current_assignment

            if current_assignment:
                current_assignment.end_at = now
                current_assignment.save(update_fields=["end_at", "updated_at"])

            new_assignment = PatientStudioAssignment.objects.create(
                patient=patient,
                studio=target_studio,
                start_at=now,
                reason=note,
            )

            Conversation.objects.filter(
                patient=patient, type=ConversationType.PATIENT_STUDIO
            ).update(studio=target_studio, updated_at=now)
            Conversation.objects.filter(
                patient=patient, type=ConversationType.INTERNAL
            ).update(studio=target_studio, updated_at=now)

        return new_assignment

    def _clone_image_message(
        self,
        conversation: Conversation,
        sender: CustomUser,
        image_file,
    ) -> Message:
        self._assert_sender_can_send(conversation, sender)

        if not image_file:
            raise ValidationError("原图文件缺失。")

        sender_role = self._get_sender_role_snapshot(conversation, sender)
        display_name = self._get_sender_display_name(conversation, sender, sender_role)
        studio_name = self._get_studio_name_snapshot(conversation)

        with transaction.atomic():
            message = Message.objects.create(
                conversation=conversation,
                sender=sender,
                sender_role_snapshot=sender_role,
                sender_display_name_snapshot=display_name,
                studio_name_snapshot=studio_name,
                content_type=MessageContentType.IMAGE,
                image=image_file,
            )
            self._touch_last_message(conversation, message.created_at)
            self._record_session_for_message(conversation, message.created_at)
        return message

    def _touch_last_message(self, conversation: Conversation, message_time) -> None:
        Conversation.objects.filter(pk=conversation.pk).update(
            last_message_at=message_time, updated_at=timezone.now()
        )

    def _record_session_for_message(
        self, conversation: Conversation, message_time: datetime
    ) -> None:
        if conversation is None or message_time is None:
            return

        session = (
            ConversationSession.objects.filter(conversation=conversation)
            .order_by("-end_at", "-id")
            .first()
        )
        if not session:
            ConversationSession.objects.create(
                conversation=conversation,
                patient=conversation.patient,
                conversation_type=conversation.type,
                start_at=message_time,
                end_at=message_time,
                message_count=1,
            )
            return

        if message_time <= session.end_at:
            session.message_count += 1
            session.save(update_fields=["message_count", "updated_at"])
            return

        if message_time - session.end_at > self.SESSION_GAP:
            ConversationSession.objects.create(
                conversation=conversation,
                patient=conversation.patient,
                conversation_type=conversation.type,
                start_at=message_time,
                end_at=message_time,
                message_count=1,
            )
            return

        session.end_at = message_time
        session.message_count += 1
        session.save(update_fields=["end_at", "message_count", "updated_at"])

    def _build_date_range(
        self, start_date: date, end_date: date
    ) -> tuple[datetime, datetime]:
        start_dt = datetime.combine(start_date, datetime.min.time())
        end_dt = datetime.combine(end_date, datetime.max.time())

        if timezone.is_aware(timezone.now()):
            start_dt = timezone.make_aware(start_dt)
            end_dt = timezone.make_aware(end_dt)

        return start_dt, end_dt

    def get_patient_chat_session_stats(
        self,
        *,
        patient: PatientProfile,
        start_date: date,
        end_date: date,
        conversation_types: Optional[list[int]] = None,
    ) -> dict:
        """
        【功能说明】
        - 统计患者在时间范围内的聊天次数、按月次数与按时段次数。

        【使用方法】
        - chat_service.get_patient_chat_session_stats(
              patient=patient,
              start_date=date(2025, 1, 1),
              end_date=date(2025, 1, 31),
          )

        【参数说明】
        - patient: PatientProfile 实例。
        - start_date: date，开始日期（含）。
        - end_date: date，结束日期（含）。
        - conversation_types: list[int] | None，限定会话类型，默认仅患者会话。

        【返回值说明】
        - dict，结构示例：
          {
            "total": 12,
            "monthly": [{"month": "2025-01", "count": 12}],
            "time_slots": {"0-7": 1, "7-10": 2, ...}
          }
        """
        if not patient or not getattr(patient, "id", None):
            raise ValidationError("患者信息无效。")
        if start_date is None or end_date is None:
            raise ValidationError("起止日期不能为空。")
        if start_date > end_date:
            raise ValidationError("起始日期不能晚于结束日期。")

        types = conversation_types or [ConversationType.PATIENT_STUDIO]
        if not types:
            raise ValidationError("会话类型不能为空。")

        start_dt, end_dt = self._build_date_range(start_date, end_date)
        tz = timezone.get_current_timezone()

        sessions = ConversationSession.objects.filter(
            patient=patient,
            conversation_type__in=types,
            start_at__gte=start_dt,
            start_at__lte=end_dt,
        )

        total = sessions.count()

        monthly_rows = (
            sessions.annotate(month=TruncMonth("start_at", tzinfo=tz))
            .values("month")
            .annotate(count=Count("id"))
            .order_by("month")
        )
        monthly = [
            {"month": item["month"].strftime("%Y-%m"), "count": item["count"]}
            for item in monthly_rows
            if item["month"]
        ]

        slot_defaults = {
            "0-7": 0,
            "7-10": 0,
            "10-13": 0,
            "13-18": 0,
            "18-21": 0,
            "21-24": 0,
        }
        slot_rows = (
            sessions.annotate(hour=ExtractHour("start_at", tzinfo=tz))
            .annotate(
                slot=Case(
                    When(hour__lt=7, then=Value("0-7")),
                    When(hour__lt=10, then=Value("7-10")),
                    When(hour__lt=13, then=Value("10-13")),
                    When(hour__lt=18, then=Value("13-18")),
                    When(hour__lt=21, then=Value("18-21")),
                    default=Value("21-24"),
                    output_field=CharField(),
                )
            )
            .values("slot")
            .annotate(count=Count("id"))
        )
        for row in slot_rows:
            slot_defaults[row["slot"]] = row["count"]

        return {
            "total": total,
            "monthly": monthly,
            "time_slots": slot_defaults,
        }
    def _assert_sender_can_send(
        self, conversation: Conversation, sender: CustomUser
    ) -> None:
        if conversation is None:
            raise ValidationError("会话不能为空。")
        if sender is None:
            raise ValidationError("发送者不能为空。")

        if conversation.type == ConversationType.PATIENT_STUDIO:
            if sender.user_type == user_choices.UserType.PATIENT:
                if not self._is_user_patient_or_family(sender, conversation.patient):
                    raise ValidationError("患者无权发送该会话消息。")
                return

            if not self._is_user_studio_member(sender, conversation.studio):
                raise ValidationError("发送者不属于该工作室。")
            if self._is_director(sender, conversation.studio):
                raise ValidationError("主任不可在患者会话发言。")
            return

        if conversation.type == ConversationType.INTERNAL:
            if sender.user_type == user_choices.UserType.PATIENT:
                raise ValidationError("患者不可在内部会话发言。")
            if not self._is_user_studio_member(sender, conversation.studio):
                raise ValidationError("发送者不属于该工作室。")
            return

        raise ValidationError("会话类型不支持。")

    def _is_user_patient_or_family(
        self, user: CustomUser, patient: PatientProfile
    ) -> bool:
        if user.user_type != user_choices.UserType.PATIENT:
            return False

        patient_profile = getattr(user, "patient_profile", None)
        if patient_profile and patient_profile.id == patient.id:
            return True

        relation = PatientRelation.objects.filter(
            patient=patient, user=user, is_active=True
        ).first()
        return relation is not None

    def _is_user_studio_member(self, user: CustomUser, studio: DoctorStudio) -> bool:
        if user.user_type == user_choices.UserType.DOCTOR:
            doctor_profile = getattr(user, "doctor_profile", None)
            if not doctor_profile:
                return False
            if doctor_profile.studio_id == studio.id:
                return True
            return studio.owner_doctor_id == doctor_profile.id

        if user.user_type == user_choices.UserType.ASSISTANT:
            assistant_profile = getattr(user, "assistant_profile", None)
            if not assistant_profile:
                return False
            return assistant_profile.doctors.filter(studio_id=studio.id).exists()

        if user.user_type == user_choices.UserType.SALES:
            sales_profile = getattr(user, "sales_profile", None)
            if not sales_profile:
                return False
            return sales_profile.doctors.filter(studio_id=studio.id).exists()

        return False

    def _is_director(self, user: CustomUser, studio: DoctorStudio) -> bool:
        doctor_profile = getattr(user, "doctor_profile", None)
        if not doctor_profile:
            return False
        return studio.owner_doctor_id == doctor_profile.id

    def _get_sender_role_snapshot(
        self, conversation: Conversation, sender: CustomUser
    ) -> int:
        if sender.user_type == user_choices.UserType.PATIENT:
            patient_profile = getattr(sender, "patient_profile", None)
            if patient_profile and patient_profile.id == conversation.patient_id:
                return MessageSenderRole.PATIENT
            relation = PatientRelation.objects.filter(
                patient=conversation.patient, user=sender, is_active=True
            ).first()
            if relation:
                return MessageSenderRole.FAMILY
            return MessageSenderRole.PATIENT

        if sender.user_type == user_choices.UserType.DOCTOR:
            if self._is_director(sender, conversation.studio):
                return MessageSenderRole.DIRECTOR
            return MessageSenderRole.PLATFORM_DOCTOR

        if sender.user_type == user_choices.UserType.ASSISTANT:
            return MessageSenderRole.ASSISTANT

        if sender.user_type == user_choices.UserType.SALES:
            return MessageSenderRole.CRC

        return MessageSenderRole.OTHER

    def _get_sender_display_name(
        self,
        conversation: Conversation,
        sender: CustomUser,
        sender_role: int,
    ) -> str:
        if sender_role == MessageSenderRole.PATIENT:
            return conversation.patient.name

        if sender_role == MessageSenderRole.FAMILY:
            relation = PatientRelation.objects.filter(
                patient=conversation.patient, user=sender, is_active=True
            ).first()
            relation_label = "家属"
            name = ""
            if relation:
                name = relation.name or ""
                relation_label = (
                    relation.relation_name
                    or relation.get_relation_type_display()
                    or "家属"
                )
            if not name:
                name = sender.display_name
            return f"{name}({relation_label})"

        if sender_role in (MessageSenderRole.DIRECTOR, MessageSenderRole.PLATFORM_DOCTOR):
            doctor_profile = getattr(sender, "doctor_profile", None)
            return doctor_profile.name if doctor_profile else sender.display_name

        if sender_role == MessageSenderRole.ASSISTANT:
            assistant_profile = getattr(sender, "assistant_profile", None)
            return assistant_profile.name if assistant_profile else sender.display_name

        if sender_role == MessageSenderRole.CRC:
            sales_profile = getattr(sender, "sales_profile", None)
            return sales_profile.name if sales_profile else sender.display_name

        return sender.display_name

    def _get_studio_name_snapshot(self, conversation: Conversation) -> str:
        if conversation.studio and conversation.studio.name:
            return conversation.studio.name
        return "Studio"
