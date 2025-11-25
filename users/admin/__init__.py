"""users admin package imports."""

from .sales import SalesProfileAdmin
from .doctors import DoctorProfileAdmin
from .assistants import AssistantProfileAdmin
from .patients import PatientProfileAdmin
from .platform import PlatformAdminUserAdmin

__all__ = [
    "SalesProfileAdmin",
    "DoctorProfileAdmin",
    "AssistantProfileAdmin",
    "PatientProfileAdmin",
    "PlatformAdminUserAdmin",
]
