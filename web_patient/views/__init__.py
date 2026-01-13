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
from .home import patient_home
from .plan import management_plan, my_medication
from .record import record_temperature, record_bp, record_spo2, record_weight, record_breath, record_sputum, record_pain, health_records,record_checkup, health_record_detail, query_last_metric
from .followup import daily_survey, get_survey_detail, submit_surveys
from .api import delete_health_metric, update_health_metric, submit_medication
from .chat import consultation_chat
from .my_followup import my_followup
from .my_examination import my_examination, examination_detail
from .health_calendar import health_calendar

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
    "patient_home",
    "management_plan",
    "my_medication",
    "record_temperature",
    "record_bp",
    "record_spo2",
    "record_weight",
    "record_breath",
    "record_sputum",
    "record_pain",
    "health_records",
    "record_checkup",
    "health_record_detail",
    "daily_survey",
    "get_survey_detail",
    "submit_surveys",
    "delete_health_metric",
    "update_health_metric",
    "submit_medication",
    "consultation_chat",
    "my_followup",
    "my_examination",
    "examination_detail",
    "health_calendar",
    "query_last_metric",
]
