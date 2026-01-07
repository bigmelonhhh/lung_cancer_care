import uuid

from django.db import models
from django.utils import timezone

from chat.models.choices import MessageContentType, MessageSenderRole
from users.models.base import TimeStampedModel


def _chat_image_upload_path(instance, filename: str) -> str:
    """Build chat image upload path."""

    date_prefix = timezone.now().strftime("%Y/%m/%d")
    safe_name = f"{uuid.uuid4().hex}_{filename}"
    return f"chat/images/{date_prefix}/{safe_name}"


class Message(TimeStampedModel):
    """
    [Purpose]
    - Persist message payloads with sender and studio snapshots.
    """

    conversation = models.ForeignKey(
        "chat.Conversation",
        on_delete=models.CASCADE,
        related_name="messages",
        verbose_name="Conversation",
        help_text="Conversation that this message belongs to.",
    )
    sender = models.ForeignKey(
        "users.CustomUser",
        on_delete=models.CASCADE,
        related_name="chat_messages",
        verbose_name="Sender",
        help_text="User who sent this message.",
    )
    sender_role_snapshot = models.PositiveSmallIntegerField(
        "Sender Role Snapshot",
        choices=MessageSenderRole.choices,
        default=MessageSenderRole.OTHER,
        help_text="Sender role at the time of sending.",
    )
    sender_display_name_snapshot = models.CharField(
        "Sender Display Name Snapshot",
        max_length=100,
        help_text="Display name captured at send time.",
    )
    studio_name_snapshot = models.CharField(
        "Studio Name Snapshot",
        max_length=100,
        help_text="Studio name captured at send time.",
    )
    content_type = models.PositiveSmallIntegerField(
        "Content Type",
        choices=MessageContentType.choices,
        default=MessageContentType.TEXT,
        help_text="Content type of the message.",
    )
    text_content = models.TextField(
        "Text Content",
        blank=True,
        help_text="Text payload for text messages.",
    )
    image = models.ImageField(
        "Image",
        upload_to=_chat_image_upload_path,
        null=True,
        blank=True,
        help_text="Image file for image messages.",
    )

    class Meta:
        verbose_name = "Message"
        verbose_name_plural = "Messages"
        indexes = [
            models.Index(fields=["conversation", "created_at"], name="idx_chat_msg_conv_time"),
        ]

    def __str__(self) -> str:
        return f"Message#{self.pk}-Conversation#{self.conversation_id}"
