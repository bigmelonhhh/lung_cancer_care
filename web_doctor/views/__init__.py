"""
web_doctor 视图模块聚合。

按功能拆分为多个子模块（如 auth、workspace），
对外仍通过 `web_doctor.views` 暴露统一接口，方便 urls 使用。
"""

from .auth import login_view, logout_view, doctor_change_password
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
    patient_medical_history_update
)

__all__ = [
    "login_view",
    "logout_view",
    "doctor_change_password",
    "doctor_workspace",
    "doctor_workspace_patient_list",
    "patient_workspace",
    "patient_workspace_section",
    "patient_treatment_cycle_create",
    "patient_cycle_medication_add",
    "patient_cycle_plan_toggle",
    "patient_plan_item_update_field",
    "patient_plan_item_toggle_day",
    "patient_profile_update",
    "patient_medical_history_update"
]
