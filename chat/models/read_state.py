from django.db import models

from users.models.base import TimeStampedModel


class ConversationReadState(TimeStampedModel):
    """
    [Purpose]
    - Track per-user read cursors for conversations.
    """

    conversation = models.ForeignKey(
        "chat.Conversation",
        on_delete=models.CASCADE,
        related_name="read_states",
        verbose_name="Conversation",
        help_text="Conversation for this read state.",
    )
    user = models.ForeignKey(
        "users.CustomUser",
        on_delete=models.CASCADE,
        related_name="conversation_read_states",
        verbose_name="User",
        help_text="User who owns this read cursor.",
    )
    last_read_message = models.ForeignKey(
        "chat.Message",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="read_state_entries",
        verbose_name="Last Read Message",
        help_text="Latest message that the user has read.",
    )

    class Meta:
        verbose_name = "Conversation Read State"
        verbose_name_plural = "Conversation Read States"
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "user"],
                name="uq_chat_read_state_conversation_user",
            ),
        ]
        indexes = [
            models.Index(fields=["conversation", "user"], name="idx_chat_read_state_conv_user"),
        ]

    def __str__(self) -> str:
        return f"ReadState#Conv{self.conversation_id}-User{self.user_id}"
