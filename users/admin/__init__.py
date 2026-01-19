"""users admin package imports."""

import types

from django.contrib import admin

from .sales import SalesProfileAdmin
from .doctors import DoctorProfileAdmin
from .doctor_studio import DoctorStudioAdmin
from .assistants import AssistantProfileAdmin
from .patients import PatientProfileAdmin
from .platform import PlatformAdminUserAdmin

MODEL_ORDER = [
    "平台管理员",
    "医生档案",
    "医生助理",
    "医生工作室",
    "患者列表",
    "销售档案",
]
_base_get_app_list = admin.site.get_app_list


def _sorted_app_list(self, request, app_label=None):
    app_list = list(_base_get_app_list(request))
    for app in app_list:
        if app["app_label"] != "users":
            continue
        app["name"] = "用户模块"
        app["models"].sort(
            key=lambda m: MODEL_ORDER.index(m["name"]) if m["name"] in MODEL_ORDER else len(MODEL_ORDER)
        )

    if app_label:
        return [app for app in app_list if app["app_label"] == app_label]
    return app_list


admin.site.get_app_list = types.MethodType(_sorted_app_list, admin.site)

__all__ = [
    "SalesProfileAdmin",
    "DoctorProfileAdmin",
    "DoctorStudioAdmin",
    "AssistantProfileAdmin",
    "PatientProfileAdmin",
    "PlatformAdminUserAdmin",
]
