import uuid

from django.db import models
from django.utils import timezone

from chat.models.choices import MessageContentType, MessageSenderRole
from users.models.base import TimeStampedModel


def _chat_image_upload_path(instance, filename: str) -> str:
    """生成聊天图片上传路径。"""

    date_prefix = timezone.now().strftime("%Y/%m/%d")
    safe_name = f"{uuid.uuid4().hex}_{filename}"
    return f"chat/images/{date_prefix}/{safe_name}"


class Message(TimeStampedModel):
    """
    消息模型。

    - 保存消息内容及发送者、工作室快照信息。
    """

    conversation = models.ForeignKey(
        "chat.Conversation",
        on_delete=models.CASCADE,
        related_name="messages",
        verbose_name="会话",
        help_text="该消息所属的会话。",
    )
    sender = models.ForeignKey(
        "users.CustomUser",
        on_delete=models.CASCADE,
        related_name="chat_messages",
        verbose_name="发送者",
        help_text="发送该消息的用户。",
    )
    sender_role_snapshot = models.PositiveSmallIntegerField(
        "发送者角色快照",
        choices=MessageSenderRole.choices,
        default=MessageSenderRole.OTHER,
        help_text="发送时的角色快照。",
    )
    sender_display_name_snapshot = models.CharField(
        "发送者展示名快照",
        max_length=100,
        help_text="发送时的展示名称快照。",
    )
    studio_name_snapshot = models.CharField(
        "工作室名称快照",
        max_length=100,
        help_text="发送时的工作室名称快照。",
    )
    content_type = models.PositiveSmallIntegerField(
        "内容类型",
        choices=MessageContentType.choices,
        default=MessageContentType.TEXT,
        help_text="消息的内容类型。",
    )
    text_content = models.TextField(
        "文本内容",
        blank=True,
        help_text="文本消息的内容。",
    )
    image = models.ImageField(
        "图片",
        upload_to=_chat_image_upload_path,
        null=True,
        blank=True,
        help_text="图片消息的文件内容。",
    )

    class Meta:
        verbose_name = "消息"
        verbose_name_plural = "消息"
        indexes = [
            models.Index(fields=["conversation", "created_at"], name="idx_chat_msg_conv_time"),
        ]

    def __str__(self) -> str:
        return f"Message#{self.pk}-Conversation#{self.conversation_id}"
