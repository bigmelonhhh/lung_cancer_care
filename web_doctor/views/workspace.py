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
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError

from users.decorators import check_doctor_or_assistant
from users.models import PatientProfile

from core.service.treatment_cycle import get_active_treatment_cycle, create_treatment_cycle
from core.models import MonitoringConfig
from core.service.monitoring import MonitoringService
from core.service.medication import get_active_medication_library
from core.service.followup import get_active_followup_library
from core.service.checkup import get_active_checkup_library
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
    context.update(_build_settings_context(patient, tc_page=None))

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
        context.update(_build_settings_context(patient, tc_page=request.GET.get("tc_page")))

    return render(request, template_name, context)


def _build_settings_context(patient: PatientProfile, tc_page: str | None = None) -> dict:
    """
    构建“管理设置（settings）”Tab 所需的上下文数据：
    - 当前进行中的疗程（active_cycle）
    - 各类监测开关配置（monitoring_config + 渲染用列表）
    - 用药 / 检查计划视图 plan_view（当前为模拟数据占位）
    """

    active_cycle = get_active_treatment_cycle(patient)
    monitoring_config, _ = MonitoringConfig.objects.get_or_create(patient=patient)

    # 患者全部疗程列表，按结束日期倒序排列（结束时间最新的在前）
    cycles_qs = patient.treatment_cycles.all().order_by("-end_date", "-start_date")
    paginator = Paginator(cycles_qs, 10)
    try:
        page_number = int(tc_page) if tc_page else 1
    except (TypeError, ValueError):
        page_number = 1
    cycle_page = paginator.get_page(page_number)

    monitoring_items = [
        {"label": "体温", "field_name": "enable_temp", "is_checked": monitoring_config.enable_temp},
        {"label": "血氧", "field_name": "enable_spo2", "is_checked": monitoring_config.enable_spo2},
        {"label": "体重", "field_name": "enable_weight", "is_checked": monitoring_config.enable_weight},
        {"label": "血压/心率", "field_name": "enable_bp", "is_checked": monitoring_config.enable_bp},
        {"label": "步数", "field_name": "enable_step", "is_checked": monitoring_config.enable_step},
    ]

    # 医院计划设置区域：从各业务 service 获取真实的“可用库”数据
    # 当前阶段仅用于前端展示计划模板，后续可与具体疗程计划绑定
    medications = get_active_medication_library()
    checkups = get_active_checkup_library()
    followups = get_active_followup_library()

    plan_view = {
        "medications": medications,
        "checkups": checkups,
        "followups": followups,
    }

    return {
        "active_cycle": active_cycle,
        "monitoring_config": monitoring_config,
        "monitoring_items": monitoring_items,
        "cycle_page": cycle_page,
        "plan_view": plan_view,
    }


@login_required
@check_doctor_or_assistant
@require_POST
def patient_monitoring_update(request: HttpRequest, patient_id: int) -> HttpResponse:
    """
    更新患者监测配置（频率 + 开关）：
    - 前端以表单形式一次性提交监测频率 + 5 个开关（体温/血氧/体重/血压/步数）
    - 每次任意字段变更时，都会提交当前整套状态
    """
    # 权限校验：确保当前登录账号可以管理该患者
    patients_qs = _get_workspace_patients(request.user, query=None)
    patient = patients_qs.filter(pk=patient_id).first()
    if patient is None:
        raise Http404("未找到患者")

    # 当前监测配置，用于在未提交频率或数据异常时兜底
    monitoring_config, _ = MonitoringConfig.objects.get_or_create(patient=patient)

    # 解析表单中的五个监测开关，未勾选的不会出现在 POST 中
    field_names = ["enable_temp", "enable_spo2", "enable_weight", "enable_bp", "enable_step"]
    switches = {field: field in request.POST for field in field_names}

    # 解析监测频率（天），若未提交或非法则回退到当前配置值
    freq_raw = request.POST.get("check_freq_days")
    try:
        check_freq_days = int(freq_raw) if freq_raw is not None else monitoring_config.check_freq_days
    except (TypeError, ValueError):
        check_freq_days = monitoring_config.check_freq_days

    MonitoringService.update_switches(
        patient,
        check_freq_days=check_freq_days,
        enable_temp=switches["enable_temp"],
        enable_spo2=switches["enable_spo2"],
        enable_weight=switches["enable_weight"],
        enable_bp=switches["enable_bp"],
        enable_step=switches["enable_step"],
    )

    # 不返回新 HTML，204 即表示“静默成功”，前端只负责视觉切换
    return HttpResponse(status=204)


@login_required
@check_doctor_or_assistant
@require_POST
def patient_treatment_cycle_create(request: HttpRequest, patient_id: int) -> HttpResponse:
    """
    为指定患者创建新的治疗疗程：
    - 使用 core.service.treatment_cycle.create_treatment_cycle 完成业务校验与创建；
    - 创建成功或失败后，均重新渲染“管理设置”Tab（包含疗程列表），由前端替换中间区域。
    """
    patients_qs = _get_workspace_patients(request.user, query=None)
    patient = patients_qs.filter(pk=patient_id).first()
    if patient is None:
        raise Http404("未找到患者")

    name = (request.POST.get("name") or "").strip()
    start_date_raw = request.POST.get("start_date") or ""
    cycle_days_raw = request.POST.get("cycle_days") or ""

    errors: list[str] = []

    # 简单字段校验与解析
    if not name:
        errors.append("请填写疗程名称。")

    from datetime import date

    try:
        start_date = date.fromisoformat(start_date_raw) if start_date_raw else date.today()
    except ValueError:
        errors.append("开始日期格式不正确，应为 YYYY-MM-DD。")
        start_date = None  # type: ignore[assignment]

    try:
        cycle_days = int(cycle_days_raw) if cycle_days_raw else 21
    except ValueError:
        errors.append("周期天数必须为整数。")
        cycle_days = 21

    if cycle_days <= 0:
        errors.append("周期天数必须大于 0。")

    if not errors and start_date:
        try:
            create_treatment_cycle(
                patient=patient,
                name=name,
                start_date=start_date,
                cycle_days=cycle_days,
            )
        except ValidationError as exc:
            errors.append(str(exc))

    # 重新构建设置页面上下文，包含疗程列表与可能的错误提示
    context: dict = {
        "patient": patient,
        "active_tab": "settings",
        "cycle_form_errors": errors,
        "cycle_form_initial": {
            "name": name or "",
            "start_date": start_date_raw or "",
            "cycle_days": cycle_days_raw or "",
        },
    }
    context.update(_build_settings_context(patient, tc_page=request.GET.get("tc_page")))

    return render(
        request,
        "web_doctor/partials/settings/main.html",
        context,
    )
