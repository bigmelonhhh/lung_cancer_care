from django.shortcuts import render
from django.http import HttpRequest, HttpResponse
from users.models import CustomUser
from users.decorators import auto_wechat_login, check_patient
from core.service.treatment_cycle import get_active_treatment_cycle
from core.service.plan_item import PlanItemService
from core.models import TreatmentCycle, choices

@auto_wechat_login
@check_patient
def management_plan(request: HttpRequest) -> HttpResponse:
    """
    【页面说明】管理计划页面 `/p/plan/`
    【功能逻辑】
    1. 展示医嘱用药计划。
    2. 展示每日体征监测计划。
    3. 展示随访问卷与复查计划。
    4. 支持接收 openid 参数，用于标识当前用户（虽然实际业务中应从 request.user 获取，此处按需求兼容 URL 传参）。
    """
    
    patient = request.patient
    
    patient_id = patient.id or None
    
    # 1. 医嘱用药计划
    medication_plan = [
        {"title": "按时用药", "status": "completed", "status_text": "已完成", "icon": "medication"}
    ]

    # 2. 每日体征监测计划
    monitoring_plan = [
        {"title": "测量体温", "status": "incomplete", "status_text": "未完成", "icon": "thermometer"},
        {"title": "测量血氧", "status": "incomplete", "status_text": "未完成", "icon": "spo2"},
        {"title": "测量血压/心率", "status": "incomplete", "status_text": "未完成", "icon": "bp"},
        {"title": "测量体重", "status": "incomplete", "status_text": "未完成", "icon": "weight"},
    ]

    # 3. 随访问卷与复查计划
    treatment_courses = [
        {
            "name": "第三疗程",
            "is_current": True,
            "items": [
                {"title": "随访问卷", "date": "2025-12-21", "status": "not_started", "status_text": "未开始", "type": "questionnaire"},
                {"title": "复查", "date": "2025-12-21", "status": "not_started", "status_text": "未开始", "type": "checkup"},
                {"title": "随访问卷", "date": "2025-12-14", "status": "completed", "status_text": "已完成", "type": "questionnaire"},
                {"title": "复查", "date": "2025-12-14", "status": "completed", "status_text": "已完成", "type": "checkup"},
            ]
        },
        {
            "name": "第二疗程",
            "is_current": False,
            "items": [
                {"title": "随访问卷", "date": "2025-11-01", "status": "incomplete", "status_text": "未完成", "type": "questionnaire"},
                {"title": "复查", "date": "2025-11-01", "status": "terminated", "status_text": "已中止", "type": "checkup"},
            ]
        },
        {
            "name": "第一疗程",
            "is_current": False,
            "items": [
                {"title": "随访问卷", "date": "2025-10-01", "status": "completed", "status_text": "已完成", "type": "questionnaire"},
                {"title": "复查", "date": "2025-10-01", "status": "completed", "status_text": "已完成", "type": "checkup"},
            ]
        }
    ]

    context = {
        "medication_plan": medication_plan,
        "monitoring_plan": monitoring_plan,
        "treatment_courses": treatment_courses,
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
    print(f"{history_medications}")
    context = {
        "patient_id": patient_id,
        "current_medications": current_medications,
        "history_medications": history_medications
    }

    return render(request, "web_patient/my_medication.html", context)
