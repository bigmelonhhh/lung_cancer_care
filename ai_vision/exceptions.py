class AiVisionError(Exception):
    """Base error for AI vision extraction."""


class AiVisionConfigurationError(AiVisionError):
    """Raised when AI vision settings are missing or invalid."""


class AiVisionResponseError(AiVisionError):
    """Raised when the model response cannot be used safely."""

