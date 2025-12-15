from django.shortcuts import render, redirect
from django.urls import reverse
from django.http import HttpRequest, HttpResponse
from users.models import CustomUser
from users import choices
from wx.services.oauth import generate_menu_auth_url
from users.decorators import auto_wechat_login, check_patient
from health_data.services.health_metric import HealthMetricService
import os
from decimal import Decimal
from users.services.patient import PatientService

TEST_PATIENT_ID = os.getenv("TEST_PATIENT_ID") or None

# 定义计划类型与健康指标的映射关系
PLAN_METRIC_MAPPING = {
    "step": {
        "key": "steps",
        "name": "步数",
        "format_func": lambda x: f"{x['value_display']}"
    },
    "temperature": {
        "key": "body_temperature",  # 假设接口中体温字段为temperature，可根据实际调整
        "name": "体温",
        "format_func": lambda x: f"{x['value_display']}"
    },
    "bp_hr": {
        "key": ["blood_pressure", "heart_rate"],
        "name": "血压心率",
        "format_func": lambda x: f"血压{x['blood_pressure']['value_display']}mmHg，心率{x['heart_rate']['value_display']}"
    },
    "spo2": {
        "key": "blood_oxygen",
        "name": "血氧饱和度",
        "format_func": lambda x: f"{x['value_display']}"
    },
    "weight": {
        "key": "weight",
        "name": "体重",
        "format_func": lambda x: f"{x['value_display']}"
    },
    "breath": {
        "key": "dyspnea",
        "name": "呼吸情况",
        "format_func": lambda x: "正常" if x else "异常"  # 根据实际数据格式调整
    },
    "sputum": {
        "key": ["sputum_color", "cough"],
        "name": "咳嗽与痰色",
        "format_func": lambda x: f"咳嗽：{x['cough'] or '无'}，痰色：{x['sputum_color'] or '无'}"
    },
    "pain": {
        "key": ["pain_incision", "pain_shoulder", "pain_bone", "pain_head"],
        "name": "疼痛情况",
        "format_func": lambda x: 
            f"切口：{x['pain_incision'] or '无'}，肩部：{x['pain_shoulder'] or '无'}，骨骼：{x['pain_bone'] or '无'}，头部：{x['pain_head'] or '无'}"
    },
    "medication": {
        "key": "medication",  # 假设接口中有用药字段，可根据实际调整
        "name": "用药提醒",
        "format_func": lambda x: "已服药" if x else "未服药"
    },
    "followup": {
        "key": "followup",  # 假设接口中有随访字段，可根据实际调整
        "name": "随访",
        "format_func": lambda x: "已完成" if x else "未完成"
    },
    "checkup": {
        "key": "checkup",  # 假设接口中有复查字段，可根据实际调整
        "name": "复查",
        "format_func": lambda x: "已完成" if x else "未完成"
    }
}

@auto_wechat_login
@check_patient
def patient_home(request: HttpRequest) -> HttpResponse:
    """
    【页面说明】患者端首页 `/p/home/`
    【模板】`web_patient/patient_home.html`，根据本人或家属身份展示功能入口与卡片。
    """
    patient = request.patient
    is_family = True
    
    # 不是家属，也不是患者，转向填写信息
    if not patient:
        onboarding_url = reverse("web_patient:onboarding")
        return redirect(onboarding_url)  

    if patient.user_id == request.user.id:
        is_family = False
    
    # 确定患者ID（测试ID或实际患者ID）
    patient_id = TEST_PATIENT_ID if TEST_PATIENT_ID else (patient.id if patient else None)
    
    #获取守护天数
    service_days = "0"
    if patient_id:  # 获取守护天数
        service_days = PatientService().get_guard_days(patient_id)
    else:
        service_days = "0"
    # 模拟每日计划数据（默认全部未完成）
    daily_plans = [
        {
            "type": "medication",
            "title": "用药提醒",
            "subtitle": "您今天还未服药",
            "status": "pending",
            "action_text": "去服药",
            "icon_class": "bg-blue-100 text-blue-600",
        },
        {
            "type": "step",
            "title": "今日步数",
            "subtitle": "您今天还未记录",
            "status": "pending",
            "action_text": "去填写",
            "icon_class": "bg-blue-100 text-blue-600",
        },
        {
            "type": "temperature",
            "title": "测量体温",
            "subtitle": "请记录今日体温",
            "status": "pending",
            "action_text": "去填写",
            "icon_class": "bg-blue-100 text-blue-600",
        },
        {
            "type": "bp_hr",
            "title": "血压心率",
            "subtitle": "请记录今日血压心率情况",
            "status": "pending",
            "action_text": "去填写",
            "icon_class": "bg-blue-100 text-blue-600",
        },
        {
            "type": "spo2",
            "title": "血氧饱和度",
            "subtitle": "请记录今日血氧饱和度",
            "status": "pending",
            "action_text": "去填写",
            "icon_class": "bg-blue-100 text-blue-600",
        },
        {
            "type": "weight",
            "title": "体重记录",
            "subtitle": "请记录今日体重",
            "status": "pending",
            "action_text": "去填写",
            "icon_class": "bg-blue-100 text-blue-600",
        },
        {
            "type": "breath",
            "title": "呼吸情况",
            "subtitle": "请自测呼吸情况",
            "status": "pending",
            "action_text": "去自测",
            "icon_class": "bg-blue-100 text-blue-600",
        },
        {
            "type": "sputum",
            "title": "咳嗽与痰色情况自测",
            "subtitle": "请自测咳嗽与痰色",
            "status": "pending",
            "action_text": "去自测",
            "icon_class": "bg-blue-100 text-blue-600",
        },
        {
            "type": "pain",
            "title": "疼痛情况记录",
            "subtitle": "请记录今日疼痛情况",
            "status": "pending",
            "action_text": "去记录",
            "icon_class": "bg-blue-100 text-blue-600",
        },
        {
            "type": "followup",
            "title": "第1次随访",
            "subtitle": "请及时完成您的第1次随访",
            "status": "pending",
            "action_text": "去完成",
            "icon_class": "bg-blue-100 text-blue-600",
        },
        {
            "type": "checkup",
            "title": "第1次复查",
            "subtitle": "请及时完成您的第1次复查",
            "status": "pending",
            "action_text": "去完成",
            "icon_class": "bg-blue-100 text-blue-600",
        },
    ]

    def get_metric_value(metric_key, data):
        """获取指标值，处理单个key和多个key的情况"""
        if isinstance(metric_key, list):
            combined_data = {k: data.get(k) for k in metric_key}
            has_data = any(v is not None for v in combined_data.values())
            return combined_data if has_data else None
        else:
            return data.get(metric_key) if data.get(metric_key) is not None else None

    # 定义需要检查的成功参数及其对应的计划类型
    # 如果URL中存在这些参数，说明刚刚提交成功，需要拉取最新数据回显
    success_params_map = {
       'temperature': 'temperature',
        'bp_hr': 'bp_hr',
        'spo2': 'spo2',
        'weight': 'weight',
        'breath_val': 'breath',
        'sputum_val': 'sputum',
        'pain_val': 'pain',
        'step': 'step',
        'medication_taken': 'medication',
        'checkup_completed': 'checkup',
    }
    # 检查是否有任何成功参数
    should_fetch_data = False
    completed_task_types = set()
    
    for param, task_type in success_params_map.items():
        if request.GET.get(param):
            should_fetch_data = True
            completed_task_types.add(task_type)
    
    # 如果需要，从接口拉取一次数据
    listData = {}
    if should_fetch_data and patient_id:
        try:
            listData = HealthMetricService.query_last_metric(int(patient_id))
            print(f"==提交后拉取健康指标数据=={listData}")
        except Exception as e:
            print(f"获取健康指标数据失败：{e}")
            listData = {}

    # 遍历计划列表，仅更新刚刚完成的任务
    for plan in daily_plans:
        plan_type = plan["type"]
        metric_config = PLAN_METRIC_MAPPING.get(plan_type)
        
        # 如果没有配置，跳过（保留默认值）
        if not metric_config:
            continue
        
        # 获取该计划对应的指标数据
        metric_data = get_metric_value(metric_config["key"], listData)
        
        # 有有效数据 → 更新为已完成状态并展示数据
        if metric_data:
            plan["status"] = "completed"
            try:
                display_value = metric_config["format_func"](metric_data)
                plan["subtitle"] = f"今日已记录：{display_value}"
            except Exception as e:
                print(f"格式化{plan_type}显示值失败: {e}")
                plan["subtitle"] = "今日已记录：数据已更新"
        # 无有效数据 → 检查是否是刚提交的任务（兜底标记为完成）
        elif plan_type in completed_task_types:
            plan["status"] = "completed"
            plan["subtitle"] = "今日已记录：提交成功"
        # 无数据且非刚提交 → 保留默认值，不做处理

            


    # ========== 任务URL映射（如果需要保留） ==========
     # "temperature": generate_menu_auth_url("web_patient:record_temperature"),
        # "bp_hr": generate_menu_auth_url("web_patient:record_bp"),
        # "spo2": generate_menu_auth_url("web_patient:record_spo2"),
        # "weight": generate_menu_auth_url("web_patient:record_weight"),
        # "breath": generate_menu_auth_url("web_patient:record_breath"),
        # "sputum": generate_menu_auth_url("web_patient:record_sputum"),
        # "pain": generate_menu_auth_url("web_patient:record_pain"),
        # "followup": generate_menu_auth_url("web_patient:record_temperature"),
        # "checkup": generate_menu_auth_url("web_patient:record_checkup"),
    task_url_mapping = {
        "step": reverse("web_patient:record_steps"),
        "temperature": reverse("web_patient:record_temperature"),
        "bp_hr": reverse("web_patient:record_bp"),
        "spo2": reverse("web_patient:record_spo2"),
        "weight": reverse("web_patient:record_weight"),
        "breath": reverse("web_patient:record_breath"),
        "sputum": reverse("web_patient:record_sputum"),
        "pain": reverse("web_patient:record_pain"),
        "followup": reverse("web_patient:daily_survey"), 
        "checkup": reverse("web_patient:record_checkup"),
    }
    

    context = {
        "patient": patient,
        "is_family": is_family,
        "service_days": service_days,
        "is_member": True,
        "daily_plans": daily_plans,
        "buy_url": generate_menu_auth_url("market:product_buy"),
        "patient_id": patient_id,
        "menuUrl": task_url_mapping
    }
    return render(request, "web_patient/patient_home.html", context)

@auto_wechat_login
@check_patient
def onboarding(request: HttpRequest) -> HttpResponse:
    """
    【页面说明】患者 onboarding 引导页 `/p/onboarding/`。
    【模板】`web_patient/onboarding.html`，用于引导首访或无档案用户完善资料。
    """
    context = {}
    if not request.user.is_authenticated:
        context["session_invalid"] = True
    return render(request, "web_patient/onboarding.html", context)