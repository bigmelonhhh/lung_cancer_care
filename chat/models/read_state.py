from django.db import models

from users.models.base import TimeStampedModel


class ConversationReadState(TimeStampedModel):
    """
    会话已读状态。

    - 记录用户在会话内的已读游标。
    """

    conversation = models.ForeignKey(
        "chat.Conversation",
        on_delete=models.CASCADE,
        related_name="read_states",
        verbose_name="会话",
        help_text="该已读状态所属的会话。",
    )
    user = models.ForeignKey(
        "users.CustomUser",
        on_delete=models.CASCADE,
        related_name="conversation_read_states",
        verbose_name="用户",
        help_text="拥有该已读游标的用户。",
    )
    last_read_message = models.ForeignKey(
        "chat.Message",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="read_state_entries",
        verbose_name="最后已读消息",
        help_text="用户已读的最新消息。",
    )

    class Meta:
        verbose_name = "会话已读状态"
        verbose_name_plural = "会话已读状态"
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
