"""
web_doctor 视图模块聚合。

按功能拆分为多个子模块（如 auth、workspace），
对外仍通过 `web_doctor.views` 暴露统一接口，方便 urls 使用。
"""

from .auth import login_view, logout_view, doctor_change_password
from .questionnaire import questionnaire_detail
from .workspace import (
    doctor_workspace,
    doctor_workspace_patient_list,
    patient_workspace,
    patient_workspace_section,
    patient_treatment_cycle_create,
    patient_cycle_medication_add,
    patient_cycle_plan_toggle,
    patient_plan_item_update_field,
    patient_plan_item_toggle_day,
    patient_profile_update,
    patient_medical_history_update,
    patient_treatment_cycle_terminate,
    patient_health_metrics_update
)
from .reports_history_data import (
    patient_report_update,
    batch_archive_images,
    create_consultation_record,
    delete_consultation_record,
)

from .mobile.views import mobile_home
from .mobile.patient_list import mobile_patient_list
from .mobile.patient_home import mobile_patient_home, mobile_patient_section
from .mobile.my_assistant import mobile_my_assistant
from .mobile.patient_records import mobile_patient_records
from .mobile.patient_todo import mobile_patient_todo_list
from .mobile.patient_basic_info import (
    mobile_patient_basic_info,
    api_mobile_patient_profile,
    api_mobile_medical_info,
    api_mobile_member_info,
)
from .mobile.health_record import (
    health_records as mobile_health_records,
    health_record_detail as mobile_health_record_detail,
    review_record_detail as mobile_review_record_detail,
    review_record_detail_data as mobile_review_record_detail_data,
)

__all__ = [
    "mobile_home",
    "mobile_patient_list",
    "mobile_patient_home",
    "mobile_patient_section",
    "mobile_patient_basic_info",
    "mobile_my_assistant",
    "mobile_patient_records",
    "mobile_patient_todo_list",
    "mobile_health_records",
    "mobile_health_record_detail",
    "mobile_review_record_detail",
    "mobile_review_record_detail_data",
    "api_mobile_patient_profile",
    "api_mobile_medical_info",
    "api_mobile_member_info",
    "login_view",
    "logout_view",
    "doctor_change_password",
    "doctor_workspace",
    "doctor_workspace_patient_list",
    "patient_workspace",
    "patient_workspace_section",
    "patient_treatment_cycle_create",
    "patient_treatment_cycle_terminate",
    "patient_cycle_medication_add",
    "patient_cycle_plan_toggle",
    "patient_plan_item_update_field",
    "patient_plan_item_toggle_day",
    "patient_profile_update",
    "patient_medical_history_update",
    "patient_health_metrics_update",
    "patient_report_update",
    "batch_archive_images",
    "create_consultation_record",
    "delete_consultation_record",
]
