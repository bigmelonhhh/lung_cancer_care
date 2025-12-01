"""
Admin registrations for core app.

Each model admin lives in its own module to avoid a single gigantic file.
"""

from .medication import MedicationAdmin  # noqa: F401
from .device import DeviceAdmin  # noqa: F401
from .feedback import FeedbackAdmin  # noqa: F401
