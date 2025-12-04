"""
医生工作台与患者工作区相关视图：
- 医生工作台首页
- 患者列表局部刷新
- 患者工作区（包含多个 Tab）
- 各 Tab（section）局部内容渲染
"""

from datetime import date

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
from core.models import MonitoringConfig, TreatmentCycle, PlanItem, choices as core_choices
from core.service.monitoring import MonitoringService
from core.service.medication import get_active_medication_library, search_medications
from core.service.followup import get_active_followup_library, get_followup_detail_items
from core.service.plan_item import PlanItemService
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
    context.update(_build_settings_context(patient, tc_page=None, selected_cycle_id=None))

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
        selected_cycle_raw = request.GET.get("cycle_id")
        try:
            selected_cycle_id = int(selected_cycle_raw) if selected_cycle_raw else None
        except (TypeError, ValueError):
            selected_cycle_id = None
        context.update(
            _build_settings_context(
                patient,
                tc_page=request.GET.get("tc_page"),
                selected_cycle_id=selected_cycle_id,
            )
        )

    return render(request, template_name, context)


def _build_settings_context(
    patient: PatientProfile, tc_page: str | None = None, selected_cycle_id: int | None = None
) -> dict:
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
    paginator = Paginator(cycles_qs, 5)
    try:
        page_number = int(tc_page) if tc_page else 1
    except (TypeError, ValueError):
        page_number = 1
    cycle_page = paginator.get_page(page_number)

    # 当前选中的疗程：
    # - 若显式传入 selected_cycle_id，则优先使用；
    # - 否则默认选中当前有效疗程 active_cycle。
    selected_cycle: TreatmentCycle | None = None
    if selected_cycle_id:
        selected_cycle = patient.treatment_cycles.filter(pk=selected_cycle_id).first()
    if selected_cycle is None:
        selected_cycle = active_cycle

    # 默认展开选中的疗程；若不存在则不展开任何卡片
    expanded_cycle_id: int | None = selected_cycle.id if selected_cycle else None

    monitoring_items = [
        {"label": "体温", "field_name": "enable_temp", "is_checked": monitoring_config.enable_temp},
        {"label": "血氧", "field_name": "enable_spo2", "is_checked": monitoring_config.enable_spo2},
        {"label": "体重", "field_name": "enable_weight", "is_checked": monitoring_config.enable_weight},
        {"label": "血压/心率", "field_name": "enable_bp", "is_checked": monitoring_config.enable_bp},
        {"label": "步数", "field_name": "enable_step", "is_checked": monitoring_config.enable_step},
    ]

    # 医院计划设置区域：从各业务 service 获取真实的“可用库”数据
    # current_day_index：用于前端判断哪些 Day 属于“历史不可编辑”
    current_day_index: int | None = None
    medications: list[dict] = []
    checkups: list[dict] = []
    followups: list[dict] = []
    active_followup: dict | None = None

    if selected_cycle:
        # 计算当前日期在疗程中的 DayIndex（最小为 1）
        delta_days = (date.today() - selected_cycle.start_date).days + 1
        current_day_index = 1 if delta_days < 1 else delta_days

        cycle_plan = PlanItemService.get_cycle_plan_view(selected_cycle.id)

        # 用药计划：仅展示当前疗程已选中的药品
        for med in cycle_plan.get("medications", []):
            if not med.get("is_active"):
                continue
            medications.append(
                {
                    "lib_id": med["library_id"],
                    "name": med["name"],
                    "type": med.get("type", ""),
                    "default_dosage": med.get("current_dosage") or med.get("default_dosage") or "",
                    "default_frequency": med.get("current_usage") or med.get("default_frequency") or "",
                    "schedule": list(med.get("schedule_days") or []),
                    "plan_item_id": med.get("plan_item_id"),
                }
            )
        
        # 复查计划：展示所有启用中的复查项目，与当前疗程下的计划状态融合
        for chk in cycle_plan.get("checkups", []):
            checkups.append(
                {
                    "lib_id": chk["library_id"],
                    "name": chk["name"],
                    "category": chk.get("related_report_type") or "",
                    "is_active": bool(chk.get("is_active")),
                    "schedule": list(chk.get("schedule_days") or []),
                    "plan_item_id": chk.get("plan_item_id"),
                }
            )

        # 随访计划：同样从 PlanItem 视图中获取
        for fu in cycle_plan.get("followups", []):
            item = {
                "lib_id": fu["library_id"],
                "name": fu["name"],
                "is_active": bool(fu.get("is_active")),
                "schedule": list(fu.get("schedule_days") or []),
                "plan_item_id": fu.get("plan_item_id"),
                "detail_config": (fu.get("interaction_config") or {}).get("details", {}),
            }
            followups.append(item)

        # 选出当前“活动”的随访计划，用于渲染问卷内容：
        # 优先选 is_active 且已存在 PlanItem 的条目；否则选任意有 PlanItem 的条目；
        # 若仍不存在，则退回到库中的第一条随访模板，至少保证界面上有一行可以开关。
        for fu in followups:
            if fu.get("is_active") and fu.get("plan_item_id"):
                active_followup = fu
                break
        if active_followup is None:
            for fu in followups:
                if fu.get("plan_item_id"):
                    active_followup = fu
                    break
        if active_followup is None and followups:
            active_followup = followups[0]

    # 其它库仍使用简单的“可用列表”供前端搜索等使用
    med_library = get_active_medication_library()
    # 随访问卷问卷内容选项：基于当前活动随访 PlanItem 的 detail_config 计算选中状态
    if active_followup:
        detail_cfg = active_followup.get("detail_config") or {}
        selected_codes = [code for code, flag in detail_cfg.items() if flag]
        followup_details = get_followup_detail_items(selected_codes)
    else:
        followup_details = get_followup_detail_items()

    plan_view = {
        "medications": medications,
        "checkups": checkups,
        "followups": followups,
        "active_followup": active_followup,
        "med_library": med_library,
        "current_day_index": current_day_index,
        # 随访计划：当前仅展示活动随访问卷的计划与问卷内容
        "followup_schedule": active_followup["schedule"] if active_followup else [],
        "followup_details": followup_details,
    }

    return {
        "active_cycle": active_cycle,
        "selected_cycle": selected_cycle,
        "monitoring_config": monitoring_config,
        "monitoring_items": monitoring_items,
        "cycle_page": cycle_page,
        "expanded_cycle_id": expanded_cycle_id,
        "plan_view": plan_view,
        "current_day_index": current_day_index,
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

    new_cycle: TreatmentCycle | None = None
    if not errors and start_date:
        try:
            new_cycle = create_treatment_cycle(
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
    selected_cycle_id = new_cycle.id if new_cycle else None
    context.update(
        _build_settings_context(patient, tc_page=request.GET.get("tc_page"), selected_cycle_id=selected_cycle_id)
    )

    return render(
        request,
        "web_doctor/partials/settings/main.html",
        context,
    )


@login_required
@check_doctor_or_assistant
@require_POST
def patient_cycle_medication_add(request: HttpRequest, patient_id: int, cycle_id: int) -> HttpResponse:
    """
    为指定疗程新增一个用药计划条目：
    - 支持通过药品名称/商品名/拼音简码模糊搜索；
    - 命中后调用 PlanItemService.toggle_item_status 将该药物加入当前疗程。
    - 操作完成后重新渲染“管理设置”Tab（包含疗程列表与用药计划）。
    """
    patients_qs = _get_workspace_patients(request.user, query=None)
    patient = patients_qs.filter(pk=patient_id).first()
    if patient is None:
        raise Http404("未找到患者")

    cycle = get_object_or_404(TreatmentCycle, pk=cycle_id, patient=patient)
    keyword = (request.POST.get("q") or "").strip()
    library_id_raw = request.POST.get("library_id") or ""

    errors: list[str] = []
    # 优先使用下拉选中的 library_id；若未选中则退回到关键字模糊搜索
    library_id: int | None = None
    if library_id_raw:
        try:
            library_id = int(library_id_raw)
        except (TypeError, ValueError):
            errors.append("所选药品 ID 无效。")

    if library_id is None:
        if not keyword:
            errors.append("请输入药品名称或拼音简码。")
        else:
            results = search_medications(keyword, limit=5)
            if not results:
                errors.append("未找到匹配的药物，请检查关键字。")
            else:
                library_id = results[0]["lib_id"]

    if library_id is not None and not errors:
        try:
            PlanItemService.toggle_item_status(
                cycle_id=cycle.id,
                category=core_choices.PlanItemCategory.MEDICATION,
                library_id=library_id,
                enable=True,
            )
        except ValidationError as exc:
            errors.append(str(exc))

    # 仅重新构建当前疗程的计划表视图，并返回 plan_table 部分，避免整个页面重绘导致滚动跳动
    settings_ctx = _build_settings_context(
        patient,
        tc_page=request.GET.get("tc_page"),
        selected_cycle_id=cycle.id,
    )
    selected_cycle = settings_ctx.get("selected_cycle")

    table_context: dict = {
        "patient": patient,
        "cycle": selected_cycle,
        "plan_view": settings_ctx.get("plan_view"),
    }

    return render(
        request,
        "web_doctor/partials/settings/plan_table.html",
        table_context,
    )


@login_required
@check_doctor_or_assistant
@require_POST
def patient_cycle_plan_toggle(request: HttpRequest, patient_id: int, cycle_id: int) -> HttpResponse:
    """
    切换某个标准库条目在指定疗程下的启用状态。
    - 目前主要用于“用药计划”行首开关：关闭时禁用该药物在本疗程中的计划（由搜索框重新开启）。
    """
    patients_qs = _get_workspace_patients(request.user, query=None)
    patient = patients_qs.filter(pk=patient_id).first()
    if patient is None:
        raise Http404("未找到患者")

    cycle = get_object_or_404(TreatmentCycle, pk=cycle_id, patient=patient)

    category_raw = (request.POST.get("category") or "").strip().lower()
    library_id_raw = request.POST.get("library_id")
    

    errors: list[str] = []
    if not library_id_raw:
        errors.append("缺少标准库条目 ID。")
    try:
        library_id = int(library_id_raw) if library_id_raw else 0
    except (TypeError, ValueError):
        library_id = 0
        errors.append("标准库条目 ID 无效。")

    # 支持药物 / 复查 / 随访三类计划开关
    if category_raw in ("medication", "medicine"):
        category = core_choices.PlanItemCategory.MEDICATION
    elif category_raw in ("checkup", "check", "exam"):
        category = core_choices.PlanItemCategory.CHECKUP
    elif category_raw in ("followup", "follow_up", "fu"):
        category = core_choices.PlanItemCategory.FOLLOW_UP
    else:
        category = None
        errors.append("不支持的计划类别。")

    if not errors and category is not None and library_id:
        enable_flag = "enable" in request.POST
        try:
            PlanItemService.toggle_item_status(
                cycle_id=cycle.id,
                category=category,
                library_id=library_id,
                enable=enable_flag,
            )
        except ValidationError as exc:
            errors.append(str(exc))

    # 复查计划：开关变化后需重新渲染该行，保证 D 日勾选与数据库状态一致
    if category == core_choices.PlanItemCategory.CHECKUP:
        if errors:
            response = HttpResponse("\n".join(errors) or "计划开关更新失败。", status=400)
            response["HX-Trigger"] = '{"plan-error": {"message": "%s"}}' % "\\n".join(errors).replace(
                '"', '\\"'
            )
            return response

        # 重新构建当前疗程的复查视图，仅返回目标项目的单行 HTML
        settings_ctx = _build_settings_context(
            patient,
            tc_page=request.GET.get("tc_page"),
            selected_cycle_id=cycle.id,
        )
        plan_view = settings_ctx.get("plan_view") or {}
        checkups = plan_view.get("checkups") or []
        target_check: dict | None = None
        for chk in checkups:
            if chk.get("lib_id") == library_id:
                target_check = chk
                break

        if target_check is None:
            return HttpResponse("", status=204)

        current_day = settings_ctx.get("current_day_index") or plan_view.get("current_day_index") or 1
        row_ctx = {
            "patient": patient,
            "cycle": cycle,
            "check": target_check,
            "current_day": current_day,
        }
        return render(
            request,
            "web_doctor/partials/settings/plan_table_checkup_row.html",
            row_ctx,
        )

    # 随访计划：开关变化后需要重新渲染整个计划表，以便携带最新的 plan_item_id 与问卷配置
    if category == core_choices.PlanItemCategory.FOLLOW_UP:
        if errors:
            response = HttpResponse("\n".join(errors) or "计划开关更新失败。", status=400)
            response["HX-Trigger"] = '{"plan-error": {"message": "%s"}}' % "\\n".join(errors).replace(
                '"', '\\"'
            )
            return response

        # 重建当前患者 + 疗程的计划视图，仅返回 plan_table 部分
        settings_ctx = _build_settings_context(
            patient,
            tc_page=request.GET.get("tc_page"),
            selected_cycle_id=cycle.id,
        )
        selected_cycle = settings_ctx.get("selected_cycle")
        table_context: dict = {
            "patient": patient,
            "cycle": selected_cycle,
            "plan_view": settings_ctx.get("plan_view"),
        }
        return render(
            request,
            "web_doctor/partials/settings/plan_table.html",
            table_context,
        )

        # 重建当前患者 + 疗程的计划视图，仅返回 plan_table 部分
        settings_ctx = _build_settings_context(
            patient,
            tc_page=request.GET.get("tc_page"),
            selected_cycle_id=cycle.id,
        )
        selected_cycle = settings_ctx.get("selected_cycle")
        table_context: dict = {
            "patient": patient,
            "cycle": selected_cycle,
            "plan_view": settings_ctx.get("plan_view"),
        }
        return render(
            request,
            "web_doctor/partials/settings/plan_table.html",
            table_context,
        )

    # 以下逻辑仅适用于“用药计划”行首开关

    # 若只是关闭（enable=False），前端通过 hx-swap="outerHTML" 清除该行即可，
    # 不再返回任何内容，避免整个设置区域大范围重绘导致滚动跳动。
    if not errors and "enable" not in request.POST:
        return HttpResponse("")

    # 打开或修正状态时，仅返回该药品对应的单行 HTML，替换当前行，减少滚动跳动。
    medications: list[dict] = []
    if not errors:
        cycle_plan = PlanItemService.get_cycle_plan_view(cycle.id)
        for med in cycle_plan.get("medications", []):
            if med.get("library_id") != library_id:
                continue
            if not med.get("is_active"):
                # 已处于未启用状态，则无行可展示
                return HttpResponse("")
            medications.append(
                {
                    "lib_id": med["library_id"],
                    "name": med["name"],
                    "type": med.get("type", ""),
                    "default_dosage": med.get("current_dosage") or med.get("default_dosage") or "",
                    "default_frequency": med.get("current_usage") or med.get("default_frequency") or "",
                    "schedule": list(med.get("schedule_days") or []),
                    "plan_item_id": med.get("plan_item_id"),
                }
            )
            break

    if errors or not medications:
        # 出现错误时，通过 HX-Trigger 抛出统一的错误事件，并退回到默认的设置页渲染
        context: dict = {
            "patient": patient,
            "active_tab": "settings",
            "cycle_form_errors": errors,
            "cycle_form_initial": {
                "name": "",
                "start_date": "",
                "cycle_days": "",
            },
        }
        context.update(
            _build_settings_context(
                patient,
                tc_page=request.GET.get("tc_page"),
                selected_cycle_id=cycle.id,
            )
        )

        response = render(
            request,
            "web_doctor/partials/settings/main.html",
            context,
        )
        if errors:
            response["HX-Trigger"] = '{"plan-error": {"message": "%s"}}' % "\\n".join(errors).replace(
                '"', '\\"'
            )
        return response

    med_ctx = {
        "patient": patient,
        "cycle": cycle,
        "med": medications[0],
    }
    return render(
        request,
        "web_doctor/partials/settings/plan_table_medication_row.html",
        med_ctx,
    )


@login_required
@check_doctor_or_assistant
@require_POST
def patient_plan_item_update_field(request: HttpRequest, patient_id: int, plan_item_id: int) -> HttpResponse:
    """
    更新某个计划条目的文本字段（剂量/用法等），用于用药计划的行内编辑。
    - 视图负责权限校验与基本参数解析；
    - 具体更新逻辑委托给 PlanItemService.update_item_field。
    """
    patients_qs = _get_workspace_patients(request.user, query=None)
    patient = patients_qs.filter(pk=patient_id).first()
    if patient is None:
        raise Http404("未找到患者")

    try:
        plan = PlanItem.objects.select_related("cycle__patient").get(pk=plan_item_id)
    except PlanItem.DoesNotExist:
        raise Http404("计划条目不存在")

    if plan.cycle.patient_id != patient.id:
        raise Http404("计划条目与患者不匹配")

    field_name = (request.POST.get("field_name") or "").strip()
    value = (request.POST.get("value") or "").strip()

    errors: list[str] = []
    if not field_name:
        errors.append("字段名称缺失。")
    else:
        try:
            PlanItemService.update_item_field(plan_item_id, field_name, value)
        except ValidationError as exc:
            errors.append(str(exc))

    context: dict = {
        "patient": patient,
        "active_tab": "settings",
        "cycle_form_errors": errors,
        "cycle_form_initial": {
            "name": "",
            "start_date": "",
            "cycle_days": "",
        },
    }
    context.update(
        _build_settings_context(
            patient,
            tc_page=request.GET.get("tc_page"),
            selected_cycle_id=plan.cycle_id,
        )
    )

    return render(
        request,
        "web_doctor/partials/settings/main.html",
        context,
    )


@login_required
@check_doctor_or_assistant
@require_POST
def patient_followup_detail_toggle(
    request: HttpRequest, patient_id: int, plan_item_id: int, code: str
) -> HttpResponse:
    """
    切换随访问卷 PlanItem 的单个问卷模块开关状态（interaction_config.details[code]）。
    - 由前端问卷内容区域的 checkbox 以 HTMX 方式调用，保持每次点击原子更新。
    """
    patients_qs = _get_workspace_patients(request.user, query=None)
    patient = patients_qs.filter(pk=patient_id).first()
    if patient is None:
        raise Http404("未找到患者")

    try:
        plan = PlanItem.objects.select_related("cycle__patient").get(pk=plan_item_id)
    except PlanItem.DoesNotExist:
        raise Http404("随访计划条目不存在")

    if plan.cycle.patient_id != patient.id:
        raise Http404("计划条目与患者不匹配")

    enabled = "enabled" in request.POST

    try:
        PlanItemService.toggle_followup_detail(plan_item_id, code, enabled)
    except ValidationError as exc:
        message = str(exc) or "随访问卷内容更新失败。"
        response = HttpResponse(message, status=400)
        response["HX-Trigger"] = '{"plan-error": {"message": "%s"}}' % message.replace('"', '\\"')
        return response

    # 不返回 HTML，HTMX 侧仅用于触发后端更新与 Toast
    return HttpResponse(status=204)


@login_required
@check_doctor_or_assistant
@require_POST
def patient_plan_item_toggle_day(
    request: HttpRequest, patient_id: int, plan_item_id: int, day: int
) -> HttpResponse:
    """
    切换某个计划条目在指定 DayIndex 下的勾选状态。
    - 不依赖前端传入的 checked 状态，而是根据当前 schedule_days 自动取反，保证幂等。
    """
    patients_qs = _get_workspace_patients(request.user, query=None)
    patient = patients_qs.filter(pk=patient_id).first()
    if patient is None:
        raise Http404("未找到患者")

    try:
        plan = PlanItem.objects.select_related("cycle__patient").get(pk=plan_item_id)
    except PlanItem.DoesNotExist:
        raise Http404("计划条目不存在")

    if plan.cycle.patient_id != patient.id:
        raise Http404("计划条目与患者不匹配")

    schedule = list(plan.schedule_days or [])
    currently_checked = day in schedule

    try:
        PlanItemService.toggle_schedule_day(plan_item_id, day, not currently_checked)
    except ValidationError as exc:
        errors = [str(exc)]
    else:
        errors = []

    context: dict = {
        "patient": patient,
        "active_tab": "settings",
        "cycle_form_errors": errors,
        "cycle_form_initial": {
            "name": "",
            "start_date": "",
            "cycle_days": "",
        },
    }
    context.update(
        _build_settings_context(
            patient,
            tc_page=request.GET.get("tc_page"),
            selected_cycle_id=plan.cycle_id,
        )
    )

    return render(
        request,
        "web_doctor/partials/settings/main.html",
        context,
    )
