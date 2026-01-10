from django.db import models

from chat.models.choices import ConversationType
from users.models.base import TimeStampedModel


class Conversation(TimeStampedModel):
    """
    会话模型。

    - 保存患者会话与内部会话容器。
    - 同一患者在每种会话类型下保持唯一。
    """

    type = models.PositiveSmallIntegerField(
        "会话类型",
        choices=ConversationType.choices,
        default=ConversationType.PATIENT_STUDIO,
        help_text="会话类型，患者会话或内部会话。",
    )
    patient = models.ForeignKey(
        "users.PatientProfile",
        on_delete=models.CASCADE,
        related_name="conversations",
        verbose_name="患者",
        help_text="会话关联的患者档案。",
    )
    studio = models.ForeignKey(
        "users.DoctorStudio",
        on_delete=models.CASCADE,
        related_name="conversations",
        verbose_name="工作室",
        help_text="会话所属工作室。",
    )
    created_by = models.ForeignKey(
        "users.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_conversations",
        verbose_name="创建人",
        help_text="创建该会话的操作人。",
    )
    last_message_at = models.DateTimeField(
        "最后消息时间",
        null=True,
        blank=True,
        help_text="该会话最新一条消息的时间。",
    )

    class Meta:
        verbose_name = "会话"
        verbose_name_plural = "会话"
        constraints = [
            models.UniqueConstraint(
                fields=["patient", "type"],
                name="uq_chat_conversation_patient_type",
            ),
        ]
        indexes = [
            models.Index(fields=["patient", "type"], name="idx_chat_conv_patient_type"),
            models.Index(fields=["studio"], name="idx_chat_conv_studio"),
        ]

    def __str__(self) -> str:
        return f"Conversation#{self.pk}-Patient#{self.patient_id}-{self.get_type_display()}"
