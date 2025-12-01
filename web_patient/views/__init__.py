from .binding import bind_landing, bind_submit
from .dashboard import patient_dashboard, onboarding
from .entry import patient_entry, send_auth_code
from .orders import patient_orders
from .profile import (
    profile_card,
    profile_edit_form,
    profile_page,
    profile_update,
)
from .family import family_management, unbind_family
from .device import device_list, api_bind_device, api_unbind_device
from .studio import my_studio
from .feedback import feedback_view
from .document import document_detail

__all__ = [
    "bind_landing",
    "bind_submit",
    "patient_dashboard",
    "onboarding",
    "patient_entry",
    "send_auth_code",
    "patient_orders",
    "profile_page",
    "profile_card",
    "profile_edit_form",
    "profile_update",
    "family_management",
    "unbind_family",
    "device_list",
    "api_bind_device",
    "api_unbind_device",
    "my_studio",
    "feedback_view",
    "document_detail",
]
