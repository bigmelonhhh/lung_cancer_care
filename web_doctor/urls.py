from django.urls import path
from . import views

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