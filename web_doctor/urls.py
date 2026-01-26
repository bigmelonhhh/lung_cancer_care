from django.urls import path
from . import views
from web_doctor.views import home
from web_doctor.views import todo_workspace
from web_doctor.views import chat_api

app_name = "web_doctor"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("doctor/mobile/home/", views.mobile_home, name="mobile_home"),
    path("logout/", views.logout_view, name="logout"),
    # path("doctor/dashboard/", views.doctor_dashboard, name="doctor_dashboard"), # 已删除
    
    path("doctor/workspace/", views.doctor_workspace, name="doctor_workspace"),
    path("doctor/todo-list/", todo_workspace.doctor_todo_list_page, name="doctor_todo_list"),
    path("doctor/todo/update_status/", todo_workspace.update_alert_status, name="doctor_todo_update_status"),
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
        "doctor/workspace/patient/<int:patient_id>/todo-sidebar/",
        todo_workspace.patient_todo_sidebar,
        name="patient_todo_sidebar",
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
        "doctor/workspace/patient/<int:patient_id>/report/<int:report_id>/update/",
        views.patient_report_update,
        name="patient_report_update",
    ),
    path(
        "doctor/workspace/patient/<int:patient_id>/reports/batch-archive/",
        views.batch_archive_images,
        name="batch_archive_images",
    ),
    path(
        "doctor/workspace/patient/<int:patient_id>/consultation/create/",
        views.create_consultation_record,
        name="create_consultation_record",
    ),
    path(
        "doctor/workspace/patient/<int:patient_id>/consultation/<int:event_id>/delete/",
        views.delete_consultation_record,
        name="delete_consultation_record",
    ),
    path(
        "doctor/workspace/patient/<int:patient_id>/home/remark/update/",
        home.patient_home_remark_update,
        name="patient_home_remark_update",
    ),
    path(
        "doctor/workspace/patient/<int:patient_id>/checkup/create/",
        home.create_checkup_record,
        name="patient_checkup_create",
    ),
    path(
        "doctor/workspace/patient/<int:patient_id>/checkup/timeline/",
        home.patient_checkup_timeline,
        name="patient_checkup_timeline",
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
    # Chat API
    path("doctor/chat/api/conversations/", chat_api.list_conversations, name="chat_api_list_conversations"),
    path("doctor/chat/api/messages/list/", chat_api.list_messages, name="chat_api_list_messages"),
    path("doctor/chat/api/messages/send/", chat_api.send_text_message, name="chat_api_send_text"),
    path("doctor/chat/api/messages/upload/", chat_api.upload_image_message, name="chat_api_upload_image"),
    path("doctor/chat/api/messages/forward/", chat_api.forward_message, name="chat_api_forward_message"),
    path("doctor/chat/api/messages/read/", chat_api.mark_read, name="chat_api_mark_read"),
    path("doctor/chat/api/messages/unread-count/", chat_api.get_unread_count, name="chat_api_get_unread_count"),
    path("doctor/chat/api/context/", chat_api.get_chat_context, name="chat_api_get_context"),
]
