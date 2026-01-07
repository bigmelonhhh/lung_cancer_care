from django.db import models

from chat.models.choices import ConversationType
from users.models.base import TimeStampedModel


class Conversation(TimeStampedModel):
    """
    [Purpose]
    - Store patient-facing and internal conversation containers.

    [Usage]
    - One patient has one conversation per type.
    """

    type = models.PositiveSmallIntegerField(
        "Conversation Type",
        choices=ConversationType.choices,
        default=ConversationType.PATIENT_STUDIO,
        help_text="Conversation type, patient-facing or internal.",
    )
    patient = models.ForeignKey(
        "users.PatientProfile",
        on_delete=models.CASCADE,
        related_name="conversations",
        verbose_name="Patient",
        help_text="Patient profile linked to this conversation.",
    )
    studio = models.ForeignKey(
        "users.DoctorStudio",
        on_delete=models.CASCADE,
        related_name="conversations",
        verbose_name="Studio",
        help_text="Studio that owns the conversation context.",
    )
    created_by = models.ForeignKey(
        "users.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_conversations",
        verbose_name="Created By",
        help_text="Operator who created the conversation.",
    )
    last_message_at = models.DateTimeField(
        "Last Message At",
        null=True,
        blank=True,
        help_text="Timestamp of the latest message in this conversation.",
    )

    class Meta:
        verbose_name = "Conversation"
        verbose_name_plural = "Conversations"
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
