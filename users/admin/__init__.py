"""users admin package."""

from .sales import SalesProfileAdmin
from .doctors import DoctorProfileAdmin
from .assistants import AssistantProfileAdmin
from .patients import PatientProfileAdmin

__all__ = [
    "SalesProfileAdmin",
    "DoctorProfileAdmin",
    "AssistantProfileAdmin",
    "PatientProfileAdmin",
]
