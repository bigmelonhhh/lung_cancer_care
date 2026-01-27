"""
医生工作台与患者工作区相关视图：
- 医生工作台首页
- 患者列表局部刷新
- 患者工作区（包含多个 Tab）
- 各 Tab（section）局部内容渲染
"""

import logging
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import random

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator
from django.utils import timezone

from users.decorators import check_doctor_or_assistant
from users.models import PatientProfile, CustomUser

from core.service.treatment_cycle import get_active_treatment_cycle, create_treatment_cycle, terminate_treatment_cycle
from core.models import TreatmentCycle, PlanItem, choices as core_choices
from core.service.monitoring import MonitoringService
from core.service.medication import get_active_medication_library, search_medications
from core.service.questionnaire import QuestionnaireService
from health_data.services.medical_history_service import MedicalHistoryService
from health_data.services.health_metric import HealthMetricService, MetricType

from core.service.plan_item import PlanItemService
from web_doctor.services.current_user import get_user_display_name
from users.services.patient import PatientService
from web_doctor.views.home import build_home_context
from patient_alerts.services.todo_list import TodoListService
from django.template.loader import render_to_string
from chat.services.chat import ChatService

logger = logging.getLogger(__name__)

_CYCLE_STATE_RANK = {
    "in_progress": 0,
    "not_started": 1,
    "completed": 2,
    "terminated": 3,
}


def _resolve_cycle_runtime_state(cycle: TreatmentCycle, today: date | None = None) -> str:
    if today is None:
        today = date.today()
    if cycle.status == core_choices.TreatmentCycleStatus.TERMINATED:
        return "terminated"
    if today < cycle.start_date:
        return "not_started"
    if cycle.end_date and today > cycle.end_date:
        return "completed"
    if cycle.status == core_choices.TreatmentCycleStatus.COMPLETED:
        return "completed"
    return "in_progress"


def _sort_cycles_for_settings(cycles: list[TreatmentCycle], today: date | None = None) -> list[TreatmentCycle]:
    if today is None:
        today = date.today()
    states = [_resolve_cycle_runtime_state(c, today=today) for c in cycles]
    if "in_progress" not in states:
        return cycles

    indexed = list(enumerate(cycles))
    indexed.sort(
        key=lambda item: (
            _CYCLE_STATE_RANK[_resolve_cycle_runtime_state(item[1], today=today)],
            item[0],
        )
    )
    return [cycle for _, cycle in indexed]


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


def enrich_patients_with_counts(user: CustomUser, patients_qs) -> list[PatientProfile]:
    """
    为患者列表附加待办事项和咨询消息计数
    """
    patients = list(patients_qs)
    chat_service = ChatService()
    
    for patient in patients:
        # 1. 查询待办消息总数
        try:
            todo_page = TodoListService.get_todo_page( 
                user=user,
                patient_id=patient.id,
                status="pending",
                page=1,
                size=999
            )
            patient.todo_count = todo_page.paginator.count
        except Exception as e:
            logger.error(f"Error fetching todo count for patient {patient.id}: {e}")
            patient.todo_count = 0

        # 2. 查询咨询消息总数
        try:
            # 获取患者会话
            conversation = chat_service.get_or_create_patient_conversation(patient=patient)
            # 获取未读消息数
            patient.consult_count = chat_service.get_unread_count(conversation, user)
        except Exception as e:
            logger.error(f"Error fetching consult count for patient {patient.id}: {e}")
            patient.consult_count = 0
            
    return patients


@login_required
@check_doctor_or_assistant
def doctor_workspace(request: HttpRequest) -> HttpResponse:
    """
    医生工作台主视图：
    - 左侧展示该医生名下患者列表（可搜索）
    - 中间区域为患者工作区入口（初次进入为空或提示）
    """
    doctor_profile, assistant_profile = _get_workspace_identities(request.user)
    patients_qs = _get_workspace_patients(request.user, request.GET.get("q"))
    patients = enrich_patients_with_counts(request.user, patients_qs)
    
    display_name = get_user_display_name(request.user)
    
    # 首页默认加载当前医生的全局待办事项
    # todo_page = TodoListService.get_todo_page(
    #     user=request.user,
    #     status="pending",
    #     page=1,
    #     size=5  # 首页侧边栏显示较多条目
    # )
    # logging.info(f"当前待办事项：{todo_page.object_list}")
    
    return render(
        request,
        "web_doctor/index.html",
        {
            "doctor": doctor_profile,
            "assistant": assistant_profile,
            "workspace_display_name": display_name,
            "patients": patients,
            "todo_list": [], # 首页初始状态为空，点击患者后加载
        },
    )


@login_required
@check_doctor_or_assistant
def doctor_workspace_patient_list(request: HttpRequest) -> HttpResponse:
    """
    医生工作台左侧“患者列表”局部刷新视图：
    - 用于搜索或分页等场景，通过 HTMX/Ajax 局部更新列表区域。
    """
    patients_qs = _get_workspace_patients(request.user, request.GET.get("q"))
    patients = enrich_patients_with_counts(request.user, patients_qs)
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

    context = {"patient": patient, "active_tab": "home"}

    # 默认加载“患者主页”内容，保证初次点击患者时中间区域完整
    context.update(build_home_context(patient))

    response_content = render_to_string("web_doctor/partials/patient_workspace.html", context, request=request)
    
    # 获取该患者的待办事项，用于侧边栏更新 (OOB)
    todo_page = TodoListService.get_todo_page(
        user=request.user,
        patient_id=patient.id,
        status="pending",
        page=1,
        size=5
    )
    patient.todo_count = todo_page.paginator.count
    todo_sidebar_html = render_to_string(
        "web_doctor/partials/todo_list_sidebar.html",
        {
            "todo_list": todo_page.object_list,
            "current_patient": patient,
            "todo_total": todo_page.paginator.count,
        },
        request=request
    )
    
    # 拼接 OOB 内容
    return HttpResponse(response_content + todo_sidebar_html)


@login_required
@check_doctor_or_assistant
def patient_workspace_section(request: HttpRequest, patient_id: int, section: str) -> HttpResponse:
    """
    患者工作区中间区域各 Tab 的局部视图：
    - 通过 URL 中的 section 动态切 Tab
    - 当前仅实现 settings（管理设置）Tab，其它 Tab 使用占位模版
    """
    try:
        patient = get_object_or_404(PatientProfile, pk=patient_id)

        # 权限校验：确保该患者在当前登录账号“可管理的患者集合”里
        allowed_patients = _get_workspace_patients(request.user, query=None).values_list("id", flat=True)
        if patient.id not in allowed_patients:
            raise Http404("未找到患者")

        context = {
            "patient": patient,
            "active_tab": section,  # 确保 Tab 高亮正确
        }
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
        elif section == "medical_history":
            template_name = "web_doctor/partials/medical_history/list.html"
            try:
                page = int(request.GET.get("page", 1))
            except (TypeError, ValueError):
                page = 1
            
            history_page = MedicalHistoryService.get_medical_history_list(patient, page=page, page_size=10)
            context.update({
                "history_page": history_page,
                "patient": patient
            })
        elif section == "home":
            template_name = "web_doctor/partials/home/home.html"
            context.update(build_home_context(patient))
        elif section == "checkup_history":
            from web_doctor.views.home import handle_checkup_history_section
            return render(
                request,
                handle_checkup_history_section(request, context),
                context
            )

        elif section == "medication_history":
            from web_doctor.views.home import handle_medication_history_section
            return render(
                request,
                handle_medication_history_section(request, context),
                context
            )

        elif section == "reports_history" or section == "reports":
            from web_doctor.views.reports_history_data import handle_reports_history_section
            # 确保 active_tab 正确设置为 'reports'，以便 tab 高亮
            context["active_tab"] = "reports"
            return render(
                request,
                handle_reports_history_section(request, context),
                context
            )
        elif section == "indicators":
            from web_doctor.views.indicators import build_indicators_context
            template_name = "web_doctor/partials/indicators/indicators.html"
            context.update(build_indicators_context(
                patient,
                cycle_id=request.GET.get("cycle_id"),
                start_date_str=request.GET.get("start_date"),
                end_date_str=request.GET.get("end_date"),
                filter_type=request.GET.get("filter_type")
            ))

        elif section == "statistics":
            from web_doctor.views.management_stats import ManagementStatsView
            view = ManagementStatsView()
            pkg_id = request.GET.get("package_id")
            selected_package_id = int(pkg_id) if pkg_id and pkg_id.isdigit() else None
            context.update(view.get_context_data(patient, selected_package_id=selected_package_id))
            template_name = "web_doctor/partials/management_stats/management_stats.html"

        return render(request, template_name, context)

    except Exception as e:
        logger.error(f"Error loading patient workspace section '{section}' for patient {patient_id}: {e}", exc_info=True)
        # 返回友好的错误提示 HTML
        error_html = f"""
        <div class="flex flex-col items-center justify-center h-full p-12 text-center text-slate-500 min-h-[400px]">
            <svg class="w-16 h-16 mb-4 text-rose-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <h3 class="text-lg font-medium text-slate-900">加载失败</h3>
            <p class="mt-2 text-sm text-slate-600">无法加载模块内容，请稍后重试。</p>
            <div class="mt-6">
                <button 
                    hx-get="{request.get_full_path()}" 
                    hx-target="#patient-content" 
                    hx-swap="innerHTML" 
                    hx-indicator="#workspace-loading-overlay"
                    class="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 transition-colors"
                >
                    重试
                </button>
            </div>
        </div>
        """
        return HttpResponse(error_html)


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

    cycles_qs = patient.treatment_cycles.all().order_by("-end_date", "-start_date")
    cycles = _sort_cycles_for_settings(list(cycles_qs))
    paginator = Paginator(cycles, 5)
    try:
        page_number = int(tc_page) if tc_page else 1
    except (TypeError, ValueError):
        page_number = 1
    cycle_page = paginator.get_page(page_number)

    # 当前选中的疗程：
    # - 若显式传入 selected_cycle_id，则优先使用；
    # - 否则默认选中疗程列表的第一条（最新的一个疗程）。
    selected_cycle: TreatmentCycle | None = None
    if selected_cycle_id:
        selected_cycle = patient.treatment_cycles.filter(pk=selected_cycle_id).first()
    
    if selected_cycle is None:
        # 如果没有指定 ID，则默认选中分页列表中的第一个疗程（如果存在）
        if cycle_page.object_list:
            selected_cycle = cycle_page.object_list[0]
        # 如果当前页没数据（例如空列表），尝试回退到 active_cycle 作为兜底
        elif active_cycle:
            selected_cycle = active_cycle

    # 默认展开选中的疗程；若不存在则不展开任何卡片
    # expanded_cycle_id: int | None = selected_cycle.id if selected_cycle else None
    expanded_cycle_id: int | None = selected_cycle.id if (selected_cycle and hasattr(selected_cycle, 'id')) else None


    # 判断当前选中的疗程是否可以终止（必须是进行中状态）
    can_terminate_selected_cycle = False
    is_cycle_editable = False
    if selected_cycle:
        runtime_state = _resolve_cycle_runtime_state(selected_cycle)
        if runtime_state == "in_progress":
            can_terminate_selected_cycle = True
        if runtime_state in ("in_progress", "not_started"):
            is_cycle_editable = True

    # 医院计划设置区域：从各业务 service 获取真实的“可用库”数据
    # current_day_index：用于前端判断哪些 Day 属于“历史不可编辑”
    current_day_index: int | None = None
    medications: list[dict] = []
    checkups: list[dict] = []
    monitorings: list[dict] = []
    questionnaires: list[dict] = []
    active_questionnaire: dict | None = None

    if selected_cycle:
        # 计算当前日期在疗程中的 DayIndex（最小为 1）
        delta_days = (date.today() - selected_cycle.start_date).days + 1
        current_day_index = 1 if delta_days < 1 else delta_days

        # cycle_plan = PlanItemService.get_cycle_plan_view(selected_cycle.id)
        cycle_plan = {}
        if hasattr(selected_cycle, 'id') and selected_cycle.id:
            try:
                cycle_plan = PlanItemService.get_cycle_plan_view(selected_cycle.id)
            except Exception as e:
                # 捕获异常，避免单个疗程计划查询失败导致整个页面报错
                logger.error(f"获取疗程 {selected_cycle.id} 计划视图失败：{e}")
                cycle_plan = {}

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

        # 问卷计划：同样从 PlanItem 视图中获取
        for q in cycle_plan.get("questionnaires", []):
            item = {
                "lib_id": q["library_id"],
                "name": q["name"],
                "is_active": bool(q.get("is_active")),
                "schedule": list(q.get("schedule_days") or []),
                "plan_item_id": q.get("plan_item_id"),
            }
            questionnaires.append(item)

        # 一般监测计划：与复查/问卷类似，从 PlanItem 视图中获取（以 MonitoringTemplate 为库）
        for m in cycle_plan.get("monitorings", []):
            monitorings.append(
                {
                    "lib_id": m["library_id"],
                    "name": m["name"],
                    "is_active": bool(m.get("is_active")),
                    "schedule": list(m.get("schedule_days") or []),
                    "plan_item_id": m.get("plan_item_id"),
                }
            )

        # 选出当前“活动”的问卷计划，用于渲染问卷内容：
        # 优先选 is_active 且已存在 PlanItem 的条目；否则选任意有 PlanItem 的条目；
        # 若仍不存在，则退回到库中的第一条随访模板，至少保证界面上有一行可以开关。
        for q in questionnaires:
            if q.get("is_active") and q.get("plan_item_id"):
                active_questionnaire = q
                break
        if active_questionnaire is None:
            for q in questionnaires:
                if q.get("plan_item_id"):
                    active_questionnaire = q
                    break
        if active_questionnaire is None and questionnaires:
            active_questionnaire = questionnaires[0]

    # 其它库仍使用简单的“可用列表”供前端搜索等使用
    med_library = get_active_medication_library()

    plan_view = {
        "medications": medications,
        "checkups": checkups,
        "questionnaires": questionnaires,
        "monitorings": monitorings,
        "active_questionnaire": active_questionnaire,
        "med_library": med_library,
        "current_day_index": current_day_index,
        # 问卷计划：当前仅展示问卷排期，不再保留旧随访模块配置
        "questionnaire_schedule": active_questionnaire["schedule"] if active_questionnaire else [],
    }

    # 获取亲情账号列表
    relations_qs = PatientService().get_patient_family_members(patient)
    relations_data = []
    for rel in relations_qs:
        # 获取关联用户的显示名称（优先取微信昵称，兜底用 username）
        
        relations_data.append({
            "name": rel.relation_name,
            "relation": rel.get_relation_type_display(),
            "phone": rel.phone,
        })

    # 构造个人资料数据
    patient_info = {
        "name": patient.name,
        "gender": patient.get_gender_display(),
        "phone": patient.phone,
        "birth_date": str(patient.birth_date) if getattr(patient, "birth_date", None) else "请填写出生日期",
        "address": getattr(patient, "address", "") or "",
        "emergency_contact": getattr(patient, "ec_name", "") or "",
        "emergency_relation": getattr(patient, "ec_relation", "") or  "",
        "emergency_phone": getattr(patient, "ec_phone", "") or  "",
        "relations": relations_data,
    }

    # 获取最新病情信息
    last_history = MedicalHistoryService.get_last_medical_history(patient)
    if last_history:
        medical_info = {
        "diagnosis": last_history.tumor_diagnosis if last_history.tumor_diagnosis is not None else "",
        "risk_factors": last_history.risk_factors if last_history.risk_factors is not None else "",
        "clinical_diagnosis": last_history.clinical_diagnosis if last_history.clinical_diagnosis is not None else "",
        "gene_test": last_history.genetic_test if last_history.genetic_test is not None else "",
        "history": last_history.past_medical_history if last_history.past_medical_history is not None else "",
        "surgery": last_history.surgical_information if last_history.surgical_information is not None else "",
        "last_updated": last_history.created_at.strftime("%Y-%m-%d") if last_history.created_at else "",  # 额外兼容created_at为None的情况
    }
    else:
        # 无记录时的默认空状态
        medical_info = {
            "diagnosis": "",
            "risk_factors": "",
            "clinical_diagnosis": "",
            "gene_test": "",
            "history": "",
            "surgery": "",
            "last_updated": "",
        }

    return {
        "active_cycle": active_cycle,
        "selected_cycle": selected_cycle,
        "can_terminate_selected_cycle": can_terminate_selected_cycle,
        "is_cycle_editable": is_cycle_editable,
        "cycle_page": cycle_page,
        "expanded_cycle_id": expanded_cycle_id,
        "plan_view": plan_view,
        "current_day_index": current_day_index,
        "patient_info": patient_info,
        "medical_info": medical_info,
    }


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
    context.update(
        _build_settings_context(patient, tc_page=request.GET.get("tc_page"), selected_cycle_id=None)
    )

    return render(
        request,
        "web_doctor/partials/settings/main.html",
        context,
    )


@login_required
@check_doctor_or_assistant
@require_POST
def patient_treatment_cycle_terminate(request: HttpRequest, patient_id: int, cycle_id: int) -> HttpResponse:
    """
    终止指定的治疗疗程：
    - 校验患者归属权
    - 校验疗程归属权
    - 调用 core.service.treatment_cycle.terminate_treatment_cycle
    - 成功或失败后重新渲染设置页面
    """
    patients_qs = _get_workspace_patients(request.user, query=None)
    patient = patients_qs.filter(pk=patient_id).first()
    if patient is None:
        raise Http404("未找到患者")

    try:
        cycle = TreatmentCycle.objects.get(pk=cycle_id, patient=patient)
    except TreatmentCycle.DoesNotExist:
        raise Http404("疗程不存在或不属于该患者")

    errors: list[str] = []
    try:
        terminate_treatment_cycle(cycle.id)
    except ValidationError as exc:
        errors.append(str(exc))

    # 重新构建上下文
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
    # 终止后，通常不再有选中的 active cycle，或者 selected_cycle 变为已终止状态
    # 这里我们让 _build_settings_context 自动决定 active_cycle（此时应该为 None 或下一个 active）
    context.update(
        _build_settings_context(
            patient,
            tc_page=request.GET.get("tc_page"),
            selected_cycle_id=None,
        )
    )

    response = render(
        request,
        "web_doctor/partials/settings/main.html",
        context,
    )
    if errors:
        response["HX-Trigger"] = '{"plan-error": {"message": "%s"}}' % "\\n".join(errors).replace('"', '\\"')
    
    return response


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
                user=request.user,
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
        "is_cycle_editable": selected_cycle.status == core_choices.TreatmentCycleStatus.IN_PROGRESS if selected_cycle else False,
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
    elif category_raw in ("questionnaire", "question", "q"):
        category = core_choices.PlanItemCategory.QUESTIONNAIRE
    elif category_raw in ("monitoring", "monitor", "mon"):
        category = core_choices.PlanItemCategory.MONITORING
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
                user=request.user,
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
            "is_cycle_editable": cycle.status == core_choices.TreatmentCycleStatus.IN_PROGRESS,
        }
        return render(
            request,
            "web_doctor/partials/settings/plan_table_checkup_row.html",
            row_ctx,
        )

    # 问卷计划：开关变化后需要重新渲染该行，以便携带最新的 plan_item_id 与问卷配置
    if category == core_choices.PlanItemCategory.QUESTIONNAIRE:
        if errors:
            response = HttpResponse("\n".join(errors) or "计划开关更新失败。", status=400)
            response["HX-Trigger"] = '{"plan-error": {"message": "%s"}}' % "\\n".join(errors).replace(
                '"', '\\"'
            )
            return response

        # 问卷计划：开关变化后，仅重新渲染该行（与 Checkup 逻辑保持一致）
        settings_ctx = _build_settings_context(
            patient,
            tc_page=request.GET.get("tc_page"),
            selected_cycle_id=cycle.id,
        )
        plan_view = settings_ctx.get("plan_view") or {}
        questionnaires = plan_view.get("questionnaires") or []
        
        target_q = None
        for q in questionnaires:
            if q.get("lib_id") == library_id:
                target_q = q
                break
        
        if target_q is None:
            return HttpResponse("", status=204)

        current_day = settings_ctx.get("current_day_index") or plan_view.get("current_day_index") or 1
        row_ctx = {
            "patient": patient,
            "cycle": cycle,
            "questionnaire": target_q,
            "current_day": current_day,
            "is_cycle_editable": cycle.status == core_choices.TreatmentCycleStatus.IN_PROGRESS,
        }
        return render(
            request,
            "web_doctor/partials/settings/plan_table_questionnaire_row.html",
            row_ctx,
        )

    # 一般监测计划：开关变化后，重新渲染对应监测行
    if category == core_choices.PlanItemCategory.MONITORING:
        if errors:
            response = HttpResponse("\n".join(errors) or "计划开关更新失败。", status=400)
            response["HX-Trigger"] = '{"plan-error": {"message": "%s"}}' % "\\n".join(errors).replace(
                '"', '\\"'
            )
            return response

        settings_ctx = _build_settings_context(
            patient,
            tc_page=request.GET.get("tc_page"),
            selected_cycle_id=cycle.id,
        )
        plan_view = settings_ctx.get("plan_view") or {}
        monitorings = plan_view.get("monitorings") or []
        target_m: dict | None = None
        for m in monitorings:
            if m.get("lib_id") == library_id:
                target_m = m
                break

        if target_m is None:
            return HttpResponse("", status=204)

        current_day = settings_ctx.get("current_day_index") or plan_view.get("current_day_index") or 1
        row_ctx = {
            "patient": patient,
            "cycle": cycle,
            "monitoring": target_m,
            "current_day": current_day,
            "is_cycle_editable": cycle.status == core_choices.TreatmentCycleStatus.IN_PROGRESS,
        }
        return render(
            request,
            "web_doctor/partials/settings/plan_table_monitoring_row.html",
            row_ctx,
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
        "is_cycle_editable": cycle.status == core_choices.TreatmentCycleStatus.IN_PROGRESS,
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
            PlanItemService.update_item_field(plan_item_id, field_name, value, request.user)
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
def patient_profile_update(request: HttpRequest, patient_id: int) -> HttpResponse:
    """
    更新患者个人档案（姓名、电话、性别、地址、紧急联系人等）。
    """
    patients_qs = _get_workspace_patients(request.user, query=None)
    patient = patients_qs.filter(pk=patient_id).first()
    if patient is None:
        raise Http404("未找到患者")

    # 构造 Service 所需的数据字典
    data = {
        "name": request.POST.get("name"),
        "phone": request.POST.get("phone"),
        "gender": request.POST.get("gender"),
        "birth_date": request.POST.get("birth_date"),
        "address": request.POST.get("address"),
        "ec_name": request.POST.get("emergency_contact"),
        "ec_relation": request.POST.get("emergency_relation"),
        "ec_phone": request.POST.get("emergency_phone"),
    }

    # 性别转换：前端传 "男"/"女"，Service 需要 1/2
    gender_map = {"男": 1, "女": 2}
    data["gender"] = gender_map.get(data.get("gender"), 0)

    try:
        PatientService().save_patient_profile(request.user, data, profile_id=patient.id)
        logger.info(f"Successfully updated patient profile for {patient_id}.")
        # 强制刷新 patient 对象，确保获取到最新数据
        patient.refresh_from_db()
    except ValidationError as exc:
        message = str(exc)
        response = HttpResponse(message, status=400)
        response["HX-Trigger"] = '{"plan-error": {"message": "%s"}}' % message.replace('"', '\\"')
        return response

    # 更新成功，重新渲染个人资料卡片
    settings_ctx = _build_settings_context(patient)
    patient_info = settings_ctx["patient_info"]
    
    return render(
        request,
        "web_doctor/partials/settings/patient_profile_card.html",
        {"patient_info": patient_info, "patient": patient}
    )


@login_required
@check_doctor_or_assistant
@require_POST
def patient_medical_history_update(request: HttpRequest, patient_id: int) -> HttpResponse:
    """
    更新（新增）患者病情记录。
    每次保存都会创建一条新的历史记录。
    """
    patients_qs = _get_workspace_patients(request.user, query=None)
    patient = patients_qs.filter(pk=patient_id).first()
    if patient is None:
        raise Http404("未找到患者")

    # 构造 Service 所需的数据字典
    # 注意：前端字段名需与 Service 期望的字段名做映射
    data = {
        "tumor_diagnosis": request.POST.get("diagnosis"),
        "risk_factors": request.POST.get("risk_factors"),
        "clinical_diagnosis": request.POST.get("clinical_diagnosis"),
        "genetic_test": request.POST.get("gene_test"),
        "past_medical_history": request.POST.get("history"),
        "surgical_information": request.POST.get("surgery"),
        # clinical_events 暂时没有对应数据库字段，暂不处理
    }

    logger.info(f"Adding new medical history for patient {patient_id}. User: {request.user.id}, Data: {data}")

    try:
        MedicalHistoryService.add_medical_history(request.user, patient, data)
        logger.info(f"Successfully added medical history for patient {patient_id}.")
    except Exception as exc:
        logger.exception(f"Unexpected error adding medical history: {exc}")
        message = "系统错误，请联系管理员。"
        response = HttpResponse(message, status=500)
        response["HX-Trigger"] = '{"plan-error": {"message": "%s"}}' % message.replace('"', '\\"')
        return response

    # 重新构建上下文以获取最新数据
    settings_ctx = _build_settings_context(patient)
    medical_info = settings_ctx["medical_info"]
    
    return render(
        request,
        "web_doctor/partials/settings/medical_info_card.html",
        {"medical_info": medical_info, "patient": patient}
    )


@login_required
@check_doctor_or_assistant
@require_POST
def patient_health_metrics_update(request: HttpRequest, patient_id: int) -> HttpResponse:
    """
    更新患者生命体征基线（手动录入）。
    """
    patients_qs = _get_workspace_patients(request.user, query=None)
    patient = patients_qs.filter(pk=patient_id).first()
    if patient is None:
        raise Http404("未找到患者")
    
    # 构造数据字典
    # 注意：PatientService.save_patient_profile 接口要求的基线数据字段名为 baseline_xxx
    # 因此需要将前端传来的简写字段名映射为接口定义的完整字段名
    data = {
        "name": patient.name,
        "phone": patient.phone,
        "address": getattr(patient, "address", "") or "",
        "ec_name": getattr(patient, "ec_name", "") or "",
        "ec_relation": getattr(patient, "ec_relation", "") or "",
        "ec_phone": getattr(patient, "ec_phone", "") or "",
        "remark": getattr(patient, "remark", "") or "", 
        "baseline_blood_oxygen": request.POST.get("blood_oxygen"),
        "baseline_blood_pressure_sbp": request.POST.get("sbp"),
        "baseline_blood_pressure_dbp": request.POST.get("dbp"),
        "baseline_heart_rate": request.POST.get("heart_rate"),
        "baseline_weight": request.POST.get("weight"),
        "baseline_body_temperature": request.POST.get("temperature"),
        "baseline_steps": request.POST.get("steps"),
    }
    
    # 清理空值，避免传递空字符串给 Decimal/Int 字段导致错误
    cleaned_data = {}
    for k, v in data.items():
        if v and str(v).strip():
            cleaned_data[k] = v.strip()
        else:
            # 对于非必填的基线字段，如果为空则传 None
            if k not in ["name", "phone"]:
                cleaned_data[k] = None
            else:
                # name/phone 必填，保留原值（虽然上面已取值，这里防守一下）
                cleaned_data[k] = v

    try:
        PatientService().save_patient_profile(request.user, cleaned_data, profile_id=patient.id)
        logger.info(f"Successfully updated health baselines for patient {patient_id}.")
        # 强制刷新以获取最新数据
        patient.refresh_from_db()
    except ValidationError as exc:
        message = str(exc)
        response = HttpResponse(message, status=400)
        response["HX-Trigger"] = '{"plan-error": {"message": "%s"}}' % message.replace('"', '\\"')
        return response
    except Exception as exc:
        logger.exception(f"Unexpected error updating baselines: {exc}")
        message = "系统错误，请联系管理员。"
        response = HttpResponse(message, status=500)
        response["HX-Trigger"] = '{"plan-error": {"message": "%s"}}' % message.replace('"', '\\"')
        return response

    # 重新构建上下文以获取最新数据
    settings_ctx = _build_settings_context(patient)
    
    response = render(
        request,
        "web_doctor/partials/settings/medical_info_card.html",
        {
            "medical_info": settings_ctx["medical_info"],
            "patient": patient,
            # "metrics_info": settings_ctx["metrics_info"] # 已移除
        }
    )
    response["HX-Trigger"] = '{"plan-success": {"message": "生命体征基线保存成功"}}'
    return response


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
        PlanItemService.toggle_schedule_day(plan_item_id, day, not currently_checked, request.user)
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
