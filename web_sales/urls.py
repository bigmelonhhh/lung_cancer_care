from django.urls import path

from .views import (
    sales_dashboard,
    sales_change_password,
    patient_entry,
    patient_detail,
)

app_name = "web_sales"

urlpatterns = [
    path("sales/dashboard/", sales_dashboard, name="sales_dashboard"),
    path(
        "sales/password/change/",
        sales_change_password,
        name="sales_change_password",
    ),
    path("sales/patient-entry/", patient_entry, name="patient_entry"),
    path(
        "sales/patient/<int:pk>/detail/",
        patient_detail,
        name="patient_detail",
    ),
]
