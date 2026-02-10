from datetime import datetime, date
import logging
from django.shortcuts import render, redirect
from django.urls import reverse
from django.http import HttpRequest, HttpResponse
from django.utils import timezone
from users.decorators import auto_wechat_login, check_patient
from core.service.tasks import get_daily_plan_summary
from core.models import choices as core_choices
from core.service.treatment_cycle import get_active_treatment_cycle
from health_data.models import MetricType, HealthMetric
from health_data.services.health_metric import HealthMetricService
from users.services.patient import PatientService

# 计划类型与健康指标的映射关系 (参考 home.py)
PLAN_METRIC_MAPPING = {
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
        "key": "followup",
        "name": "随访",
        "format_func": lambda x: "已完成" if x else "未完成"
    },
    "复查": {
        "key": "checkup",
        "name": "复查",
        "format_func": lambda x: "已完成" if x else "未完成"
    }
}

@auto_wechat_login
@check_patient
def health_calendar(request: HttpRequest) -> HttpResponse:
    """
    【页面说明】患者端健康日历 `/p/health_calendar/`
    """
    patient = request.patient
    
    # 1. 获取日期参数，默认为今天
    date_str = request.GET.get('date')
    if date_str:
        try:
            target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            target_date = timezone.localdate()
    else:
        target_date = timezone.localdate()

    active_cycle = get_active_treatment_cycle(patient)
    action_enabled = False
    if active_cycle:
        cycle_end = active_cycle.end_date
        if cycle_end is None:
            action_enabled = target_date >= active_cycle.start_date
        else:
            action_enabled = active_cycle.start_date <= target_date <= cycle_end
        
    # 2. 获取该日期的计划摘要
    summary_list = []
    # 只有当目标日期不晚于今天时，才查询计划
    if target_date <= timezone.localdate():
        summary_list = get_daily_plan_summary(patient, task_date=target_date)
        logging.info(f"[health_calendar] 获取计划摘要: {summary_list}")
    
    # 3. 获取该日期的具体指标数据（用于回显数值）
    # 注意：这里需要查询指定日期的指标，而不是最新指标
    daily_metrics = {}
    
    # 辅助函数：查询指定日期、指定类型的最后一条指标
    def query_metric_for_date(p_id, m_type, t_date):
        # 构造当天的起止时间
        start_dt = timezone.make_aware(datetime.combine(t_date, datetime.min.time()))
        end_dt = timezone.make_aware(datetime.combine(t_date, datetime.max.time()))
        
        metric = HealthMetric.objects.filter(
            patient_id=p_id,
            metric_type=m_type,
            measured_at__range=(start_dt, end_dt)
        ).order_by("-measured_at").first()
        
        if metric:
            return {
                "name": MetricType(m_type).label,
                "value_main": metric.value_main,
                "value_sub": metric.value_sub,
                "value_display": metric.display_value,
                "measured_at": metric.measured_at,
                "source": metric.source,
            }
        return None

    metric_types_to_query = set()
    for item in summary_list:
        task_type_val = item.get("task_type")
        if task_type_val in (
            core_choices.PlanItemCategory.CHECKUP,
            core_choices.PlanItemCategory.QUESTIONNAIRE,
        ):
            continue

        title_val = item.get("title") or ""
        if "步数" in title_val:
            continue
        if "用药" in title_val:
            metric_types_to_query.add(MetricType.USE_MEDICATED)
        elif "体温" in title_val:
            metric_types_to_query.add(MetricType.BODY_TEMPERATURE)
        elif "血压" in title_val or "心率" in title_val:
            metric_types_to_query.add(MetricType.BLOOD_PRESSURE)
            metric_types_to_query.add(MetricType.HEART_RATE)
        elif "血氧" in title_val:
            metric_types_to_query.add(MetricType.BLOOD_OXYGEN)
        elif "体重" in title_val:
            metric_types_to_query.add(MetricType.WEIGHT)

    for m_type in sorted(metric_types_to_query):
        daily_metrics[m_type] = query_metric_for_date(patient.id, m_type, target_date)

    metric_plan_cache = request.session.get("metric_plan_cache") or {}
    cached_plans = metric_plan_cache.get(target_date.strftime("%Y-%m-%d")) or {}

    # 4. 构建视图数据
    daily_plans = []
    for item in summary_list:
        title_val = item.get("title")
        status_val = item.get("status")
        is_completed = status_val == core_choices.TaskStatus.COMPLETED
        task_type_val = item.get("task_type")
        skip_metric_query = task_type_val in (
            core_choices.PlanItemCategory.CHECKUP,
            core_choices.PlanItemCategory.QUESTIONNAIRE,
        )
        
        # 默认值
        plan_data = {
            "type": "unknown",
            "title": title_val,
            "subtitle": "请按时完成",
            "status": "completed" if is_completed else "pending",
            "action_text": "去完成",
            "icon_class": "bg-blue-100 text-blue-600",
        }
        
        # 过滤掉步数
        if "步数" in title_val:
            continue

        # 类型映射逻辑 (与 home.py 保持一致)
        if "用药" in title_val:
            plan_data.update({
                "type": "medication",
                "subtitle": "您还未服药" if not is_completed else "已服药",
                "action_text": "去服药"
            })
        elif "体温" in title_val:
            plan_data.update({
                "type": "temperature",
                "subtitle": "请记录体温",
                "action_text": "去填写"
            })
        elif "血压" in title_val or "心率" in title_val:
            # 检查是否已经添加了 bp_hr 类型的任务
            if any(p["type"] == "bp_hr" for p in daily_plans):
                continue
            plan_data.update({
                "type": "bp_hr",
                "title": "血压/心率监测",
                "subtitle": "请记录血压心率",
                "action_text": "去填写"
            })
        elif "血氧" in title_val:
            plan_data.update({
                "type": "spo2",
                "subtitle": "请记录血氧饱和度",
                "action_text": "去填写"
            })
        elif "体重" in title_val:
            plan_data.update({
                "type": "weight",
                "subtitle": "请记录体重",
                "action_text": "去填写"
            })
        elif "随访" in title_val or "问卷" in title_val:
            q_ids = item.get("questionnaire_ids", [])
            action_url = reverse("web_patient:daily_survey")
            if q_ids:
                 ids_str = ",".join(map(str, q_ids))
                 action_url = f"{action_url}?ids={ids_str}" 
            plan_data.update({
                "type": "followup",
                "subtitle": "请及时完成随访" if not is_completed else "已完成",
                "action_text": "去完成",
                "url": action_url
            })
        elif "复查" in title_val:
            plan_data.update({
                "type": "checkup",
                "subtitle": "请及时完成复查" if not is_completed else "已完成",
                "action_text": "去完成"
            })
        else:
            continue

        if skip_metric_query:
            plan_data["status"] = (
                "completed"
                if status_val == core_choices.TaskStatus.COMPLETED
                else "pending"
            )
            if plan_data["type"] == "checkup":
                plan_data["subtitle"] = "已完成" if plan_data["status"] == "completed" else "未完成"
            if plan_data["type"] == "followup":
                plan_data["subtitle"] = "已完成" if plan_data["status"] == "completed" else "未完成"
        else:
            cached_plan = cached_plans.get(plan_data["type"]) if cached_plans else None
            if cached_plan:
                cached_status = cached_plan.get("status")
                if cached_status in ("completed", "pending"):
                    plan_data["status"] = cached_status
                cached_subtitle = cached_plan.get("subtitle")
                if cached_subtitle:
                    plan_data["subtitle"] = cached_subtitle

        # 尝试填充具体的数值（如果已完成）
        metric_config = None
        plan_type = plan_data["type"]
        
        # 查找配置
        if plan_type == "temperature": metric_config = PLAN_METRIC_MAPPING.get("体温")
        elif plan_type == "bp_hr": metric_config = PLAN_METRIC_MAPPING.get("血压")
        elif plan_type == "spo2": metric_config = PLAN_METRIC_MAPPING.get("血氧")
        elif plan_type == "weight": metric_config = PLAN_METRIC_MAPPING.get("体重")
        elif plan_type == "medication": metric_config = PLAN_METRIC_MAPPING.get("用药提醒")
        
        if metric_config and plan_data["status"] == "completed":
            metric_key = metric_config["key"]
            metric_val = None
            
            if isinstance(metric_key, list):
                # 组合数据 (如血压心率)
                combined_data = {k: daily_metrics.get(k) for k in metric_key}
                # 只要有一个非空即可
                if any(v is not None for v in combined_data.values()):
                    metric_val = combined_data
            else:
                metric_val = daily_metrics.get(metric_key)
                
            if metric_val:
                try:
                    display_value = metric_config["format_func"](metric_val)
                    plan_data["subtitle"] = f"已记录：{display_value}"
                except Exception:
                    plan_data["subtitle"] = "已完成"

        daily_plans.append(plan_data)

    # 排序
    sort_order = {
        "medication": 1,
        "spo2": 2,
        "bp_hr": 3,
        "weight": 4,
        "temperature": 5,
        "checkup": 6,
        "followup": 7
    }
    daily_plans.sort(key=lambda x: sort_order.get(x.get("type"), 999))

    # URL 映射 (用于跳转)
    task_url_mapping = {
        "temperature": reverse("web_patient:record_temperature"),
        "bp_hr": reverse("web_patient:record_bp"),
        "spo2": reverse("web_patient:record_spo2"),
        "weight": reverse("web_patient:record_weight"),
        "followup": reverse("web_patient:daily_survey"), 
        "checkup": reverse("web_patient:record_checkup"),
    }

    context = {
        "patient": patient,
        "target_date": target_date,
        "daily_plans": daily_plans,
        "menuUrl": task_url_mapping,
        "today": timezone.localdate(), # 用于前端判断是否是今天
        "action_enabled": action_enabled,
    }
    
    # AJAX 请求返回局部模板
    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('ajax'):
        return render(request, "web_patient/partials/_daily_plan_list.html", context)

    return render(request, "web_patient/health_calendar.html", context)
