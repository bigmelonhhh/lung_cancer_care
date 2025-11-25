"""users admin package."""

from .sales import SalesProfileAdmin
from .doctors import DoctorProfileAdmin
from .assistants import AssistantProfileAdmin

__all__ = ["SalesProfileAdmin", "DoctorProfileAdmin", "AssistantProfileAdmin"]
