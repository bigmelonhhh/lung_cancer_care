"""
医生工作台与患者工作区相关视图：
- 医生工作台首页
- 患者列表局部刷新
- 患者工作区（包含多个 Tab）
- 各 Tab（section）局部内容渲染
"""

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from users.decorators import check_doctor_or_assistant
from users.models import PatientProfile

from core.service.treatment_cycle import get_active_treatment_cycle
from core.models import MonitoringConfig
from web_doctor.services.current_user import get_user_display_name


def _get_workspace_identities(user):
    """
    根据当前登录账号获取工作台身份：
    - 医生账号：返回 (doctor_profile, None)
    - 医助账号：返回 (None, assistant_profile)
    """
    doctor_profile = getattr(user, "doctor_profile", None)
    assistant_profile = getattr(user, "assistant_profile", None)
    if not doctor_profile and not assistant_profile:
        # 对于既不是医生也不是医助的账号，不允许进入医生工作台
        raise Http404("当前账号未绑定医生/医生助理档案")
    return doctor_profile, assistant_profile


def _get_workspace_patients(user, query: str | None):
    """
    工作台患者列表查询逻辑：
    - 医生账号：返回该医生名下的所有在管患者
    - 医助账号：返回其负责医生的所有在管患者（多对多汇总）
    """
    doctor_profile, assistant_profile = _get_workspace_identities(user)

    qs = PatientProfile.objects.filter(is_active=True)
    if doctor_profile:
        qs = qs.filter(doctor=doctor_profile)
    elif assistant_profile:
        doctors_qs = assistant_profile.doctors.all()
        qs = qs.filter(doctor__in=doctors_qs)
    else:
        qs = PatientProfile.objects.none()

    if query:
        query = query.strip()
        if query:
            qs = qs.filter(Q(name__icontains=query) | Q(phone__icontains=query))
    return qs.order_by("name").distinct()


@login_required
@check_doctor_or_assistant
def doctor_workspace(request: HttpRequest) -> HttpResponse:
    """
    医生工作台主视图：
    - 左侧展示该医生名下患者列表（可搜索）
    - 中间区域为患者工作区入口（初次进入为空或提示）
    """
    doctor_profile, assistant_profile = _get_workspace_identities(request.user)
    patients = _get_workspace_patients(request.user, request.GET.get("q"))
    display_name = get_user_display_name(request.user)
    return render(
        request,
        "web_doctor/index.html",
        {
            "doctor": doctor_profile,
            "assistant": assistant_profile,
            "workspace_display_name": display_name,
            "patients": patients,
        },
    )


@login_required
@check_doctor_or_assistant
def doctor_workspace_patient_list(request: HttpRequest) -> HttpResponse:
    """
    医生工作台左侧“患者列表”局部刷新视图：
    - 用于搜索或分页等场景，通过 HTMX/Ajax 局部更新列表区域。
    """
    patients = _get_workspace_patients(request.user, request.GET.get("q"))
    return render(
        request,
        "web_doctor/partials/patient_list.html",
        {
            "patients": patients,
        },
    )


@login_required
@check_doctor_or_assistant
def patient_workspace(request: HttpRequest, patient_id: int) -> HttpResponse:
    """
    患者工作区主页面：
    - 右侧中间区域的主框架
    - 默认进入时加载“管理设置（settings）”Tab 的内容
    """
    # 与工作台列表使用同一规则：医生看自己患者，医助看所有绑定医生的患者
    patients_qs = _get_workspace_patients(request.user, query=None).select_related("user")
    patient = patients_qs.filter(pk=patient_id).first()
    if patient is None:
        raise Http404("未找到患者")

    context = {"patient": patient, "active_tab": "settings"}

    # 默认加载“管理设置”内容，保证初次点击患者时中间区域完整
    context.update(_build_settings_context(patient))

    return render(
        request,
        "web_doctor/partials/patient_workspace.html",
        context,
    )


@login_required
@check_doctor_or_assistant
def patient_workspace_section(request: HttpRequest, patient_id: int, section: str) -> HttpResponse:
    """
    患者工作区中间区域各 Tab 的局部视图：
    - 通过 URL 中的 section 动态切 Tab
    - 当前仅实现 settings（管理设置）Tab，其它 Tab 使用占位模版
    """
    patient = get_object_or_404(PatientProfile, pk=patient_id)

    # 权限校验：确保该患者在当前登录账号“可管理的患者集合”里
    allowed_patients = _get_workspace_patients(request.user, query=None).values_list("id", flat=True)
    if patient.id not in allowed_patients:
        raise Http404("未找到患者")

    context = {"patient": patient}
    template_name = "web_doctor/partials/sections/placeholder.html"

    if section == "settings":
        template_name = "web_doctor/partials/settings/main.html"
        context.update(_build_settings_context(patient))

    return render(request, template_name, context)


def _build_settings_context(patient: PatientProfile) -> dict:
    """
    构建“管理设置（settings）”Tab 所需的上下文数据：
    - 当前进行中的疗程（active_cycle）
    - 各类监测开关配置（monitoring_config + 渲染用列表）
    - 用药 / 检查计划视图 plan_view（当前为模拟数据占位）
    """

    active_cycle = get_active_treatment_cycle(patient)
    monitoring_config, _ = MonitoringConfig.objects.get_or_create(patient=patient)

    monitoring_items = [
        {"label": "体温", "field_name": "enable_temp", "is_checked": monitoring_config.enable_temp},
        {"label": "血氧", "field_name": "enable_spo2", "is_checked": monitoring_config.enable_spo2},
        {"label": "体重", "field_name": "enable_weight", "is_checked": monitoring_config.enable_weight},
        {"label": "血压/心率", "field_name": "enable_bp", "is_checked": monitoring_config.enable_bp},
        {"label": "步数", "field_name": "enable_step", "is_checked": monitoring_config.enable_step},
    ]

    # TODO: 后续替换为 PlanItemService.get_cycle_plan_view(active_cycle.id)
    plan_view = {"medications": [], "checkups": []}
    if active_cycle:
        plan_view = {
            "medications": [
                {
                    "lib_id": 1,
                    "name": "卡铂",
                    "type": "化疗",
                    "item_id": 101,
                    "is_active": True,
                    "dosage": "300ml",
                    "schedule": [1, 8, 15],
                },
                {
                    "lib_id": 2,
                    "name": "培美曲塞",
                    "type": "化疗",
                    "item_id": None,
                    "is_active": False,
                    "dosage": "1000ml",
                    "schedule": [],
                },
            ],
            "checkups": [
                {"lib_id": 1, "name": "血常规", "is_active": True, "schedule": [1, 8, 15]},
                {"lib_id": 2, "name": "胸部CT", "is_active": False, "schedule": []},
            ],
        }

    return {
        "active_cycle": active_cycle,
        "monitoring_config": monitoring_config,
        "monitoring_items": monitoring_items,
        "plan_view": plan_view,
    }
