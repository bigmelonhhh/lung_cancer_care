from django.db import models


class ConversationType(models.IntegerChoices):
    """会话类型枚举。"""

    PATIENT_STUDIO = 1, "患者会话"
    INTERNAL = 2, "内部会话"


class MessageContentType(models.IntegerChoices):
    """消息内容类型枚举。"""

    TEXT = 1, "文本"
    IMAGE = 2, "图片"


class MessageSenderRole(models.IntegerChoices):
    """发送者角色快照枚举。"""

    PATIENT = 1, "患者"
    FAMILY = 2, "家属"
    DIRECTOR = 3, "主任"
    PLATFORM_DOCTOR = 4, "平台医生"
    ASSISTANT = 5, "医生助理"
    CRC = 6, "CRC"
    OTHER = 99, "其他"
