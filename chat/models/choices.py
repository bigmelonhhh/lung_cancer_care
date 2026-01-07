from django.db import models


class ConversationType(models.IntegerChoices):
    """Conversation type enum."""

    PATIENT_STUDIO = 1, "Patient Studio"
    INTERNAL = 2, "Internal"


class MessageContentType(models.IntegerChoices):
    """Message content type enum."""

    TEXT = 1, "Text"
    IMAGE = 2, "Image"


class MessageSenderRole(models.IntegerChoices):
    """Sender role snapshot enum."""

    PATIENT = 1, "Patient"
    FAMILY = 2, "Family"
    DIRECTOR = 3, "Director"
    PLATFORM_DOCTOR = 4, "Platform Doctor"
    ASSISTANT = 5, "Assistant"
    CRC = 6, "CRC"
    OTHER = 99, "Other"
