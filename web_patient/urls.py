from django.urls import path

from . import views

app_name = "web_patient"

urlpatterns = [
    path("dashboard/", views.patient_dashboard, name="patient_dashboard"),
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
