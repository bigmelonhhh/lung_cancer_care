from django.urls import path

from . import views

app_name = "web_patient"

urlpatterns = [
    path("dashboard/", views.patient_dashboard, name="patient_dashboard"),
    path("home/", views.patient_home, name="patient_home"),
    path("plan/", views.management_plan, name="management_plan"),
    path("medication/", views.my_medication, name="my_medication"),
    path("health/records/", views.health_records, name="health_records"),
    path("health/record/detail/", views.health_record_detail, name="health_record_detail"),
    path("record/temperature/", views.record_temperature, name="record_temperature"),
    path("record/bp/", views.record_bp, name="record_bp"),
    path("record/spo2/", views.record_spo2, name="record_spo2"),
    path("record/weight/", views.record_weight, name="record_weight"),
    path("record/breath/", views.record_breath, name="record_breath"),
    path("record/sputum/", views.record_sputum, name="record_sputum"),
    path("record/pain/", views.record_pain, name="record_pain"),
    path("record/checkup/", views.record_checkup, name="record_checkup"),
    path("followup/daily/", views.daily_survey, name="daily_survey"),
    path("record/steps/", views.record_steps, name="record_steps"),
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
]
