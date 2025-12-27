from django.urls import path
from . import views
from web_doctor.views import home

app_name = "web_doctor"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    # path("doctor/dashboard/", views.doctor_dashboard, name="doctor_dashboard"), # 已删除
    
    path("doctor/workspace/", views.doctor_workspace, name="doctor_workspace"),
    path(
        "doctor/workspace/patient-list/",
        views.doctor_workspace_patient_list,
        name="doctor_workspace_patient_list",
    ),
    path(
        "doctor/workspace/patient/<int:patient_id>/",
        views.patient_workspace,
        name="patient_workspace",
    ),
    path(
        "doctor/workspace/patient/<int:patient_id>/treatment-cycle/create/",
        views.patient_treatment_cycle_create,
        name="patient_treatment_cycle_create",
    ),
    path(
        "doctor/workspace/patient/<int:patient_id>/cycle/<int:cycle_id>/terminate/",
        views.patient_treatment_cycle_terminate,
        name="patient_treatment_cycle_terminate",
    ),
    path(
        "doctor/workspace/patient/<int:patient_id>/cycle/<int:cycle_id>/medication/add/",
        views.patient_cycle_medication_add,
        name="patient_cycle_medication_add",
    ),
    path(
        "doctor/workspace/patient/<int:patient_id>/cycle/<int:cycle_id>/plan-toggle/",
        views.patient_cycle_plan_toggle,
        name="patient_cycle_plan_toggle",
    ),
    path(
        "doctor/workspace/patient/<int:patient_id>/plan-item/<int:plan_item_id>/field/",
        views.patient_plan_item_update_field,
        name="patient_plan_item_update_field",
    ),
    path(
        "doctor/workspace/patient/<int:patient_id>/plan-item/<int:plan_item_id>/day/<int:day>/",
        views.patient_plan_item_toggle_day,
        name="patient_plan_item_toggle_day",
    ),
    path(
        "doctor/workspace/patient/<int:patient_id>/profile/update/",
        views.patient_profile_update,
        name="patient_profile_update",
    ),
    path(
        "doctor/workspace/patient/<int:patient_id>/medical_history/update/",
        views.patient_medical_history_update,
        name="patient_medical_history_update",
    ),
    path(
        "doctor/workspace/patient/<int:patient_id>/health-metrics/update/",
        views.patient_health_metrics_update,
        name="patient_health_metrics_update",
    ),
    path(
        "doctor/workspace/patient/<int:patient_id>/home/remark/update/",
        home.patient_home_remark_update,
        name="patient_home_remark_update",
    ),
    path(
        "doctor/workspace/patient/<int:patient_id>/medication/stop/",
        home.patient_medication_stop,
        name="patient_medication_stop",
    ),
    path(
        "doctor/workspace/patient/<int:patient_id>/questionnaire/detail/",
        views.questionnaire_detail,
        name="questionnaire_detail",
    ),
    path(
        "doctor/workspace/patient/<int:patient_id>/<str:section>/",
        views.patient_workspace_section,
        name="patient_workspace_section",
    ),
    path(
        "doctor/password/change/",
        views.doctor_change_password,
        name="doctor_change_password",
    ),
]
