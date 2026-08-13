from django.shortcuts import render
from django.http import HttpRequest, HttpResponse
from users.models import CustomUser
from users.decorators import auto_wechat_login, check_patient, require_plan_access
from core.service.treatment_cycle import get_active_treatment_cycle
from core.service.plan_item import PlanItemService
from core.models import TreatmentCycle, choices
from core.service.tasks import get_daily_plan_summary
from health_data.models import MetricType
from health_data.services.monitoring_catalog import (
    get_monitoring_definition_by_metric_type,
    resolve_monitoring_definition,
)
from web_patient.services.management_plan import build_treatment_course_sections


_MANAGEMENT_MONITORING_GROUPS = (
    ("spo2", (MetricType.BLOOD_OXYGEN,)),
    ("bp_hr", (MetricType.BLOOD_PRESSURE, MetricType.HEART_RATE)),
    ("temperature", (MetricType.BODY_TEMPERATURE,)),
    ("weight", (MetricType.WEIGHT,)),
    ("step", (MetricType.STEPS,)),
    ("glucose", (MetricType.BLOOD_GLUCOSE,)),
    ("ketone", (MetricType.BLOOD_KETONE,)),
    ("uric_acid", (MetricType.URIC_ACID,)),
)


def _build_management_monitoring_plan(
    daily_plans: list[dict],
    *,
    include_steps: bool = True,
) -> list[dict]:
    """构建管理计划页固定监测类目及其今日任务状态。"""
    tasks_by_group: dict[str, list[dict]] = {}
    for task in daily_plans:
        definition = resolve_monitoring_definition(
            metric_type=task.get("metric_type"),
            title=task.get("title") or "",
        )
        if definition:
            tasks_by_group.setdefault(definition.home_type, []).append(task)

    monitoring_plan = []
    for group_type, metric_types in _MANAGEMENT_MONITORING_GROUPS:
        if group_type == "step" and not include_steps:
            continue
        group_tasks = tasks_by_group.get(group_type, [])
        if not group_tasks:
            status = ""
            status_text = "今日无计划"
        elif any(
            task.get("status") == choices.TaskStatus.COMPLETED
            for task in group_tasks
        ):
            status = "completed"
            status_text = "已完成"
        else:
            status = "incomplete"
            status_text = "未完成"

        if group_type == "bp_hr":
            title = "测量血压/心率"
        else:
            definition = get_monitoring_definition_by_metric_type(metric_types[0])
            title = f"测量{definition.title}"

        monitoring_plan.append(
            {
                "title": title,
                "status": status,
                "status_text": status_text,
                "icon": group_type,
            }
        )

    return monitoring_plan

@auto_wechat_login
@check_patient
@require_plan_access
def management_plan(request: HttpRequest) -> HttpResponse:
    """
    【页面说明】TODO 管理计划页面 `/p/plan/` 
    【功能逻辑】
    1. 展示医嘱用药计划。
    2. 展示每日体征监测计划。
    3. 展示随访问卷与复查计划。
    4. 支持接收 openid 参数，用于标识当前用户（虽然实际业务中应从 request.user 获取，此处按需求兼容 URL 传参）。
    """
    
    patient = request.patient
    home_plan_access = request.home_plan_access
    
    patient_id = patient.id or None

    # 获取今日计划数据
    daily_plans = []
    try:
        daily_plans = get_daily_plan_summary(patient)
    except Exception:
        daily_plans = []

    # 1. 医嘱用药计划
    medication_plan = []
    # 查找是否有MEDICATION类型的任务或标题包含"用药"
    med_task = next((p for p in daily_plans if p.get('task_type') == 'MEDICATION' or "用药" in p.get('title', "")), None)
    
    if med_task:
        # status 0 = pending, 1 = completed
        status = "completed" if med_task.get('status') == choices.TaskStatus.COMPLETED else "incomplete"
        status_text = "已完成" if status == "completed" else "未完成"
        medication_plan.append({
            "title": med_task.get('title', "按时用药"),
            "status": status,
            "status_text": status_text,
            "icon": "medication"
        })

    # 2. 常规监测计划
    monitoring_plan = _build_management_monitoring_plan(
        daily_plans,
        include_steps=home_plan_access.can_view_steps,
    )

    # 3. 随访问卷与复查计划
    treatment_course_sections = build_treatment_course_sections(
        patient,
        current_only=not home_plan_access.can_view_history,
    )

    context = {
        "medication_plan": medication_plan,
        "monitoring_plan": monitoring_plan,
        "treatment_course_sections": treatment_course_sections,
        "patient_id": patient_id
    }
    
    return render(request, "web_patient/management_plan.html", context)

@auto_wechat_login
@check_patient
def my_medication(request: HttpRequest) -> HttpResponse:
    """
    【页面说明】我的用药页面 `/p/medication/`
    【功能逻辑】
    1. 展示当前用药列表。
    2. 展示历史用药列表。
    3. 支持空状态展示。
    """
    patient = request.patient
    patient_id = patient.id or None

    # 1. 获取当前用药数据（真实数据）
    active_cycle = get_active_treatment_cycle(patient)
    current_medications = []
    
    if active_cycle:
        plan_view = PlanItemService.get_cycle_plan_view(active_cycle.id)
        # 筛选出当前生效的药物
        active_meds = [m for m in plan_view["medications"] if m["is_active"]]
        
        if active_meds:
            drugs = []
            for med in active_meds:
                drugs.append({
                    "name": med["name"],
                    "frequency": med["current_usage"],
                    "dosage": med["current_dosage"],
                    "usage": med.get("method_display", "")
                })
            
            current_medications.append({
                "course_name": active_cycle.name,
                "start_date": active_cycle.start_date.strftime("%Y-%m-%d") if active_cycle.start_date else "--",
                "end_date": None, # 当前正在进行，无结束日期
                "drugs": drugs
            })

    # 2. 获取历史用药数据（真实数据，最近10条）
    history_qs = TreatmentCycle.objects.filter(patient=patient)
    if active_cycle:
        history_qs = history_qs.exclude(id=active_cycle.id)
    
    # 过滤掉没有生效用药计划的疗程，并按开始时间倒序排列
    history_qs = history_qs.filter(
        plan_items__category=choices.PlanItemCategory.MEDICATION,
        plan_items__status=choices.PlanItemStatus.ACTIVE
    ).distinct().order_by("-start_date")[:10]
    
    history_medications = []
    for cycle in history_qs:
        plan_view = PlanItemService.get_cycle_plan_view(cycle.id)
        active_meds = [m for m in plan_view["medications"] if m["is_active"]]
        
        if active_meds:
            drugs = []
            for med in active_meds:
                drugs.append({
                    "name": med["name"],
                    "frequency": med["current_usage"],
                    "dosage": med["current_dosage"],
                    "usage": med.get("method_display", "")
                })
                
            history_medications.append({
                "course_name": cycle.name,
                "start_date": cycle.start_date.strftime("%Y-%m-%d") if cycle.start_date else "--",
                "end_date": cycle.end_date.strftime("%Y-%m-%d") if cycle.end_date else "--",
                "drugs": drugs
            })
    context = {
        "patient_id": patient_id,
        "current_medications": current_medications,
        "history_medications": history_medications
    }

    return render(request, "web_patient/my_medication.html", context)
