from django.shortcuts import render, redirect
from django.urls import reverse
from django.http import HttpRequest, HttpResponse
from users.models import CustomUser
from users import choices
from wx.services.oauth import generate_menu_auth_url
from users.decorators import auto_wechat_login, check_patient
from health_data.services.health_metric import HealthMetricService
from health_data.models import MetricType
import os
from decimal import Decimal
from users.services.patient import PatientService
from datetime import datetime
from django.utils import timezone  # 处理时区转换

from core.service.tasks import get_daily_plan_summary
from core.models import choices as core_choices

# 定义计划类型与健康指标的映射关系
PLAN_METRIC_MAPPING = {
    "step": {
        "key": MetricType.STEPS,
        "name": "步数",
        "format_func": lambda x: f"{x['value_display']}"
    },
    "体温": {
        "key": MetricType.BODY_TEMPERATURE,
        "name": "体温",
        "format_func": lambda x: f"{x['value_display']}"
    },
    "血压": {
        "key": [MetricType.BLOOD_PRESSURE, MetricType.HEART_RATE],
        "name": "血压心率",
        "format_func": lambda x: f"血压{x[MetricType.BLOOD_PRESSURE]['value_display'] if x.get(MetricType.BLOOD_PRESSURE) else '--'}mmHg，心率{x[MetricType.HEART_RATE]['value_display'] if x.get(MetricType.HEART_RATE) else '--'}"
    },
    "血氧": {
        "key": MetricType.BLOOD_OXYGEN,
        "name": "血氧饱和度",
        "format_func": lambda x: f"{x['value_display']}"
    },
    "体重": {
        "key": MetricType.WEIGHT,
        "name": "体重",
        "format_func": lambda x: f"{x['value_display']}"
    },
    "用药提醒": {
        "key": MetricType.USE_MEDICATED,
        "name": "用药提醒",
        "format_func": lambda x: "已服药" if x else "未服药"
    },
    "随访": {
        "key": "followup",  # 假设接口中有随访字段，可根据实际调整
        "name": "随访",
        "format_func": lambda x: "已完成" if x else "未完成"
    },
    "复查": {
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
    patient_id =  patient.id or None
    # 获取守护天数
    service_days = "0"
    daily_plans = []
    
    if patient_id:  # 获取守护天数
        served_days, remaining_days = PatientService().get_guard_days(patient)
        service_days = served_days
        
        # 调用接口获取今日计划数据
        try:
            summary_list = get_daily_plan_summary(patient)
            
            # 将接口数据转换为前端需要的格式
            for item in summary_list:
                task_type_val = item.get("task_type")
                status_val = item.get("status")
                title_val = item.get("title")
                
                # 默认值
                plan_data = {
                    "type": "unknown",
                    "title": title_val,
                    "subtitle": "请按时完成",
                    "status": "pending" if status_val == 0 else "completed",
                    "action_text": "去完成",
                    "icon_class": "bg-blue-100 text-blue-600",
                }
                
                # 根据 title 或 task_type 映射前端类型
                # 注意：这里主要依赖 title 来做映射，因为 task_type 比较宽泛（如 MONITORING=4 包含多种监测）
                # 过滤掉步数任务，不显示在计划列表里
                if "步数" in title_val:
                    continue

                if "用药" in title_val:
                    plan_data.update({
                        "type": "medication",
                        "subtitle": "您今天还未服药" if status_val == 0 else "今日已服药",
                        "action_text": "去服药"
                    })
                elif "体温" in title_val:
                    plan_data.update({
                        "type": "temperature",
                        "subtitle": "请记录今日体温",
                        "action_text": "去填写"
                    })
                elif "血压" in title_val or "心率" in title_val:
                    # 检查是否已经添加了 bp_hr 类型的任务
                    has_bp_hr = any(p["type"] == "bp_hr" for p in daily_plans)
                    if has_bp_hr:
                        continue
                        
                    plan_data.update({
                        "type": "bp_hr",
                        "title": "血压/心率监测",  # 合并后的标题
                        "subtitle": "请记录今日血压心率情况",
                        "action_text": "去填写"
                    })
                elif "血氧" in title_val:
                    plan_data.update({
                        "type": "spo2",
                        "subtitle": "请记录今日血氧饱和度",
                        "action_text": "去填写"
                    })
                elif "体重" in title_val:
                    plan_data.update({
                        "type": "weight",
                        "subtitle": "请记录今日体重",
                        "action_text": "去填写"
                    })
                elif "随访" in title_val or "问卷" in title_val:
                    plan_data.update({
                        "type": "followup",
                        "subtitle": "请及时完成您的随访任务",
                        "action_text": "去完成"
                    })
                elif "复查" in title_val:
                    plan_data.update({
                        "type": "checkup",
                        "subtitle": "请及时完成您的复查任务",
                        "action_text": "去完成"
                    })
                # 去除呼吸、咳嗽、疼痛等映射
                else:
                    # 如果匹配不到已知类型，暂不展示，或者作为通用类型展示
                    # 根据需求：去除不存在的类型，所以这里选择不添加到 daily_plans
                    continue
                
                daily_plans.append(plan_data)
                
        except Exception as e:
            daily_plans = []
            
    else:
        service_days = "0"
        
    # 移除手动添加步数任务的逻辑
    # 如果接口没有返回步数任务，手动添加步数任务（作为固定项）
    # has_step = any(p["type"] == "step" for p in daily_plans)
    # if not has_step:
    #    ...

    def get_metric_value(metric_key, data):
        """获取指标值，处理单个key和多个key的情况"""
        if not metric_key or not data:
            return None
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
        'followup': 'followup',
    }
    # 检查是否有任何成功参数
    should_fetch_data = False
    completed_task_types = set()
    
    for param, task_type in success_params_map.items():
        if request.GET.get(param):
            should_fetch_data = True
            completed_task_types.add(task_type)
            
    # 特别处理：如果 URL 中有 followup=true，也标记为 followup 完成
    if request.GET.get('followup') == 'true':
        should_fetch_data = True
        completed_task_types.add('followup')
    
    
     # ========== 新增：日期校验辅助函数 ==========
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
        today = timezone.now().date()
        # 3. 对比年月日是否一致
        return local_time.date() == today

    # 如果需要，从接口拉取一次数据
    listData = {}
    # 今日步数
    step_count = "0"
    if patient_id:
        try:
            listData = HealthMetricService.query_last_metric(int(patient_id))
            if MetricType.STEPS in listData and listData[MetricType.STEPS] is not None:
                steps_info = listData[MetricType.STEPS]
                # 仅当步数是今日数据时才更新，否则保持0
                if is_today_data(steps_info):
                    step_count = steps_info.get('value_display', '0')
        except Exception as e:
            listData = {}
            
    # 遍历计划列表，仅更新刚刚完成的任务
    for plan in daily_plans:
        plan_type = plan.get("type")
        if not plan_type: continue
        
        # 1. 尝试从 mapping 中获取配置（优先使用中文名匹配，如果不行则直接用 type）
        # mapping 的 key 目前是中文名，如 "体温"，但 plan['type'] 是英文 "temperature"
        # 所以我们需要一个反向查找或者调整 mapping 的 key
        # 简单起见，我们在上面构建 daily_plans 时已经保证 type 是英文
        # 我们可以遍历 mapping 找到对应的 key
        
        metric_config = None
        for k, v in PLAN_METRIC_MAPPING.items():
            # 这里的逻辑有点绕，因为 PLAN_METRIC_MAPPING 的 key 既有英文又有中文
            # 我们假设 plan['title'] 可以用来匹配 mapping 的 key
            # 修改逻辑：主要使用 plan['type'] 来匹配 mapping 的 key (现在 mapping key 已改为中文)
            # 或者使用 plan['title'] 来匹配
            if k == plan.get("title") or (v['name'] == plan.get("title")) or k == plan_type:
                metric_config = v
                break
        
        # 如果通过 title 没找到，尝试通过 type 找（需要遍历 mapping 的 value 里的 key）
        # 现在的 PLAN_METRIC_MAPPING key 是中文，value 里的 key 是 MetricType 枚举
        # 我们可以增加一种匹配方式：通过 type 英文名来匹配
        if not metric_config:
             if plan_type == "temperature": metric_config = PLAN_METRIC_MAPPING.get("体温")
             elif plan_type == "bp_hr": metric_config = PLAN_METRIC_MAPPING.get("血压")
             elif plan_type == "spo2": metric_config = PLAN_METRIC_MAPPING.get("血氧")
             elif plan_type == "weight": metric_config = PLAN_METRIC_MAPPING.get("体重")
             elif plan_type == "medication": metric_config = PLAN_METRIC_MAPPING.get("用药提醒")
             elif plan_type == "followup": metric_config = PLAN_METRIC_MAPPING.get("随访")
             elif plan_type == "checkup": metric_config = PLAN_METRIC_MAPPING.get("复查")

        # 如果没有配置，跳过（保留默认值）
        if not metric_config:
            continue
        
        # 默认仅处理步数，提交后处理所有类型
        # if not should_fetch_data and plan_type != "step":
        #     continue 
        
        # 获取该计划对应的指标数据
        metric_data = get_metric_value(metric_config["key"], listData)
        
        # 有有效数据 → 先判断是否是今日数据，再更新状态
        if metric_data:
            # 找到原始指标信息（用于获取measured_at）
            # 兼容metric_key是单个值/列表的情况
            metric_key = metric_config["key"]
            raw_metric_info = None
            if isinstance(metric_key, list):
                # 取第一个非空的指标信息（如bp_hr可能包含血压/心率）
                for k in metric_key:
                    if listData.get(k):
                        raw_metric_info = listData[k]
                        break
            else:
                raw_metric_info = listData.get(metric_key)
            
            # 非今日数据 → 跳过更新，保留默认状态
            if not is_today_data(raw_metric_info):
                continue
            
            # 今日数据 → 更新为已完成状态并展示数据
            plan["status"] = "completed"
            try:
                display_value = metric_config["format_func"](metric_data)
                plan["subtitle"] = f"今日已记录：{display_value}"
            except Exception as e:
                plan["subtitle"] = "今日已记录"
        # 无有效数据 → 检查是否是刚提交的任务（兜底标记为完成）
        elif plan_type in completed_task_types:
            plan["status"] = "completed"
            plan["subtitle"] = "今日已记录：问卷提交成功"
            
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
        "daily_plans": daily_plans,
        "buy_url": generate_menu_auth_url("market:product_buy"),
        "patient_id": patient_id,
        "menuUrl": task_url_mapping,
        "step_count": step_count,
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