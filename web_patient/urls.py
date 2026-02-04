from django.urls import path

from . import views
from .views import chat_api
from .views import my_report

app_name = "web_patient"

urlpatterns = [
    path("dashboard/", views.patient_dashboard, name="patient_dashboard"),
    path("reminder/settings/", views.reminder_settings, name="reminder_settings"),
    path("health_calendar/", views.health_calendar, name="health_calendar"),
    path("home/", views.patient_home, name="patient_home"),
    path("plan/", views.management_plan, name="management_plan"),
    path("medication/", views.my_medication, name="my_medication"),
    path("health/records/", views.health_records, name="health_records"),
    path("health/record/detail/", views.health_record_detail, name="health_record_detail"),
    path("health/review/record/detail/", views.review_record_detail, name="review_record_detail"),
    path("record/temperature/", views.record_temperature, name="record_temperature"),
    path("record/bp/", views.record_bp, name="record_bp"),
    path("record/spo2/", views.record_spo2, name="record_spo2"),
    path("record/weight/", views.record_weight, name="record_weight"),
    path("record/checkup/", views.record_checkup, name="record_checkup"),
    path("record/image/<int:image_id>/delete/", views.delete_report_image, name="delete_report_image"),
    path("api/last_metric/", views.query_last_metric, name="query_last_metric"),
    path("api/membership/status/", views.membership_status, name="membership_status"),
    path("followup/daily/", views.daily_survey, name="daily_survey"),
    path("followup/my/", views.my_followup, name="my_followup"),
    path("examination/my/", views.my_examination, name="my_examination"),
    path("examination/detail/<int:task_id>/", views.examination_detail, name="examination_detail"),
    path("examination/reports/", my_report.my_examination, name="report_list"),
    path("examination/reports/upload/", my_report.upload_report, name="report_upload"),
    path("examination/reports/delete/", my_report.delete_report, name="report_delete"),
    path("api/survey/<int:survey_id>/", views.get_survey_detail, name="get_survey_detail"),
    path("api/survey/submit/", views.submit_surveys, name="submit_surveys"),
    path("family/", views.family_management, name="family_management"),
    path("family/unbind/", views.unbind_family, name="unbind_family"),
    path("profile/", views.profile_page, name="profile_page"),
    path("onboarding/", views.onboarding, name="onboarding"),
    path("entry/", views.patient_entry, name="entry"),
    path("api/send-code/", views.send_auth_code, name="send_auth_code"),
    path(
        "profile/<int:patient_id>/card/",
        views.profile_card,
        name="profile_card",
    ),
    path(
        "profile/<int:patient_id>/edit/",
        views.profile_edit_form,
        name="profile_edit",
    ),
    path(
        "profile/<int:patient_id>/update/",
        views.profile_update,
        name="profile_update",
    ),
    path("orders/", views.patient_orders, name="orders"),
    path("bind/<int:patient_id>/", views.bind_landing, name="bind_landing"),
    path("bind/<int:patient_id>/submit/", views.bind_submit, name="bind_submit"),
    path("devices/", views.device_list, name="device_list"),
    path("devices/bind/", views.api_bind_device, name="api_bind_device"),
    path("devices/unbind/", views.api_unbind_device, name="api_unbind_device"),
    path("studio/", views.my_studio, name="my_studio"),
    path("feedback/", views.feedback_view, name="feedback"),
    path("docs/<str:key>/", views.document_detail, name="document_detail"),
    path("consultation/chat/", views.consultation_chat, name="consultation_chat"),
    # API endpoints
    path("api/health/metric/delete/", views.delete_health_metric, name="delete_health_metric"),
    path("api/health/metric/update/", views.update_health_metric, name="update_health_metric"),
    path(
        "api/health/review/record/images/",
        views.review_record_detail_data,
        name="review_record_detail_data",
    ),
    path("api/medication/submit/", views.submit_medication, name="submit_medication"),
    # Chat API
    path("chat/api/messages/list/", chat_api.list_messages, name="chat_api_list_messages"),
    path("chat/api/messages/send/", chat_api.send_text_message, name="chat_api_send_text"),
    path("chat/api/messages/upload/", chat_api.upload_image_message, name="chat_api_upload_image"),
    path("chat/api/messages/read/", chat_api.mark_read, name="chat_api_mark_read"),
]
