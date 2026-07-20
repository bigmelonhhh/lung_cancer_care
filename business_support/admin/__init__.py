"""
Admin registrations for business_support models.

Each admin class lives in its own module to keep the files manageable.
"""

from .device import DeviceAdmin  # noqa: F401
from .device_provider import DeviceProviderAdmin  # noqa: F401
from .document import SystemDocumentAdmin  # noqa: F401
from .feedback import FeedbackAdmin  # noqa: F401
from .sms_log import SMSLogAdmin  # noqa: F401
