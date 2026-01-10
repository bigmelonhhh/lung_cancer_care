from django.db import models

from chat.models.choices import ConversationType
from users.models.base import TimeStampedModel


class ConversationSession(TimeStampedModel):
    """
    会话分段记录。

    - 用于统计聊天次数（按 30 分钟间隔切分）。
    """

    conversation = models.ForeignKey(
        "chat.Conversation",
        on_delete=models.CASCADE,
        related_name="sessions",
        verbose_name="会话",
        help_text="会话分段所属的会话。",
    )
    patient = models.ForeignKey(
        "users.PatientProfile",
        on_delete=models.CASCADE,
        related_name="conversation_sessions",
        verbose_name="患者",
        help_text="该会话分段所属的患者。",
    )
    conversation_type = models.PositiveSmallIntegerField(
        "会话类型",
        choices=ConversationType.choices,
        default=ConversationType.PATIENT_STUDIO,
        help_text="会话类型快照。",
    )
    start_at = models.DateTimeField(
        "开始时间",
        help_text="本次会话分段的开始时间。",
    )
    end_at = models.DateTimeField(
        "结束时间",
        help_text="本次会话分段的结束时间。",
    )
    message_count = models.PositiveIntegerField(
        "消息数量",
        default=1,
        help_text="本次会话分段内的消息数量。",
    )

    class Meta:
        verbose_name = "会话分段"
        verbose_name_plural = "会话分段"
        indexes = [
            models.Index(fields=["patient", "start_at"], name="idx_chat_sess_patient_start"),
            models.Index(fields=["conversation", "start_at"], name="idx_chat_sess_conv_start"),
            models.Index(
                fields=["patient", "conversation_type", "start_at"],
                name="idx_chat_sess_patient_type",
            ),
        ]

    def __str__(self) -> str:
        return f"Session#{self.pk}-Conv{self.conversation_id}-Patient{self.patient_id}"
