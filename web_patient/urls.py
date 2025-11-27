from django.urls import path

from . import views

app_name = "web_patient"

urlpatterns = [
    path("dashboard/", views.patient_dashboard, name="patient_dashboard"),
    path("onboarding/", views.onboarding, name="onboarding"),
    path("orders/", views.patient_orders, name="orders"),
    path("bind/<int:patient_id>/", views.bind_landing, name="bind_landing"),
    path("bind/<int:patient_id>/submit/", views.bind_submit, name="bind_submit"),
]
