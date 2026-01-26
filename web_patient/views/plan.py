from django.shortcuts import render
from django.http import HttpRequest, HttpResponse
from users.models import CustomUser
from users.decorators import auto_wechat_login, check_patient, require_membership
from core.service.treatment_cycle import get_active_treatment_cycle
from core.service.plan_item import PlanItemService
from core.models import TreatmentCycle, choices
from core.service.tasks import get_daily_plan_summary
from health_data.services.health_metric import HealthMetricService
from health_data.models import MetricType
from django.utils import timezone

def is_today_data(metric_info: dict) -> bool:
    """
    判断指标数据的measured_at是否为今日（年月日匹配）
    :param metric_info: 指标字典（如steps、blood_pressure），需包含measured_at字段
    :return: True=今日数据，False=非今日数据
    """
    if not metric_info or 'measured_at' not in metric_info:
        return False
    # 1. 提取UTC时间并转换为本地时区（Django配置的TIME_ZONE，如Asia/Shanghai）
    utc_time = metric_info['measured_at']
    local_time = timezone.localtime(utc_time)
    # 2. 获取当前本地时间的年月日
    today = timezone.localdate()
    # 3. 对比年月日是否一致
    return local_time.date() == today

@auto_wechat_login
@check_patient
@require_membership
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
    
    patient_id = patient.id or None

    # 获取今日计划数据
    daily_plans = []
    try:
        daily_plans = get_daily_plan_summary(patient)
    except Exception:
        daily_plans = []

    # 获取今日指标数据
    metric_data = {}
    if patient_id:
        try:
            metric_data = HealthMetricService.query_last_metric(int(patient_id))
        except Exception:
            metric_data = {}
    
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
    MONITORING_CONFIG = [
        {"type": "spo2", "title": "测量血氧", "metric_type": MetricType.BLOOD_OXYGEN, "icon": "spo2"},
        {"type": "bp_hr", "title": "测量血压/心率", "metric_type": [MetricType.BLOOD_PRESSURE, MetricType.HEART_RATE], "icon": "bp_hr"},
        {"type": "temperature", "title": "测量体温", "metric_type": MetricType.BODY_TEMPERATURE, "icon": "temperature"},
        {"type": "weight", "title": "测量体重", "metric_type": MetricType.WEIGHT, "icon": "weight"},
        {"type": "step", "title": "测量步数", "metric_type": MetricType.STEPS, "icon": "step"},
    ]

    monitoring_plan = []
    for item in MONITORING_CONFIG:
        # 检查是否在今日计划中
        in_plan = False
        
        # 定义关键字映射
        keywords = []
        if item['type'] == 'spo2': keywords = ["血氧"]
        elif item['type'] == 'bp_hr': keywords = ["血压", "心率"]
        elif item['type'] == 'temperature': keywords = ["体温"]
        elif item['type'] == 'weight': keywords = ["体重"]
        elif item['type'] == 'step': keywords = ["步数"]
        
        for task in daily_plans:
            title = task.get('title', "")
            if any(k in title for k in keywords):
                in_plan = True
                break
        
        status = ""
        status_text = "今日无计划"
        
        if in_plan:
            # 检查是否有今日数据
            has_data = False
            m_types = item['metric_type'] if isinstance(item['metric_type'], list) else [item['metric_type']]
            
            for mt in m_types:
                data_info = metric_data.get(mt)
                if is_today_data(data_info):
                    has_data = True
                    break
            
            if has_data:
                status = "completed"
                status_text = "已完成"
            else:
                status = "incomplete"
                status_text = "未完成"
                
        monitoring_plan.append({
            "title": item['title'],
            "status": status,
            "status_text": status_text,
            "icon": item['icon']
        })

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
@require_membership
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
