from datetime import datetime

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from core.models import choices as core_choices
from core.service.tasks import get_daily_plan_summary
from core.service.treatment_cycle import get_active_treatment_cycle
from health_data.models import MetricType
from health_data.services.health_metric import HealthMetricService
from health_data.services.monitoring_catalog import (
    get_monitoring_definitions,
    resolve_monitoring_definition,
)
from users.decorators import auto_wechat_login, check_patient


CALENDAR_MONITORING_SUBTITLES = {
    "temperature": "请记录体温",
    "bp_hr": "请记录血压心率",
    "spo2": "请记录血氧饱和度",
    "weight": "请记录体重",
    "glucose": "请记录血糖",
    "ketone": "请记录血酮",
    "uric_acid": "请记录尿酸",
}


CALENDAR_PLAN_SORT_ORDER = {
    "medication": 1,
    "spo2": 2,
    "bp_hr": 3,
    "weight": 4,
    "temperature": 5,
    "glucose": 6,
    "ketone": 7,
    "uric_acid": 8,
    "checkup": 9,
    "followup": 10,
}


NEW_GENERAL_MONITORING_TYPES = {
    MetricType.BLOOD_GLUCOSE,
    MetricType.BLOOD_KETONE,
    MetricType.URIC_ACID,
}


def _query_calendar_metrics(patient_id, target_date, summary_list):
    """按计划涉及的指标类型查询指定日期最后一条有效记录。"""
    metric_types_to_query = set()
    for item in summary_list:
        task_type = item.get("task_type")
        if task_type in (
            core_choices.PlanItemCategory.CHECKUP,
            core_choices.PlanItemCategory.QUESTIONNAIRE,
        ):
            continue

        title = item.get("title") or ""
        if "用药" in title:
            metric_types_to_query.add(MetricType.USE_MEDICATED)
            continue

        definition = resolve_monitoring_definition(
            metric_type=item.get("metric_type"),
            title=title,
        )
        if not definition or not definition.show_in_home_list:
            continue
        if definition.home_type == "bp_hr":
            metric_types_to_query.update(
                {MetricType.BLOOD_PRESSURE, MetricType.HEART_RATE}
            )
        else:
            metric_types_to_query.add(definition.metric_type)

    daily_metrics = {}
    for metric_type in sorted(metric_types_to_query):
        metric_result = HealthMetricService.query_last_metric_for_date(
            patient_id=patient_id,
            target_date=target_date,
            metric_type=metric_type,
        )
        daily_metrics[metric_type] = metric_result.get(metric_type)
    return daily_metrics


def _format_calendar_metric_value(plan_type, definition, daily_metrics):
    """返回日历卡片已录入值；无对应记录时返回空字符串。"""
    if plan_type == "bp_hr":
        blood_pressure = daily_metrics.get(MetricType.BLOOD_PRESSURE)
        heart_rate = daily_metrics.get(MetricType.HEART_RATE)
        if not blood_pressure and not heart_rate:
            return ""
        return (
            f"血压{blood_pressure['value_display'] if blood_pressure else '--'}mmHg，"
            f"心率{heart_rate['value_display'] if heart_rate else '--'}"
        )

    if plan_type == "medication":
        return "已服药" if daily_metrics.get(MetricType.USE_MEDICATED) else ""

    if not definition:
        return ""
    metric = daily_metrics.get(definition.metric_type)
    if not metric:
        return ""
    if definition.metric_type == MetricType.BLOOD_GLUCOSE:
        return (
            f"{metric.get('measurement_context_display')} "
            f"{metric['value_display']}"
        ).strip()
    return metric["value_display"]


def _build_calendar_task_urls():
    """构建健康日历任务录入入口，监测类入口统一标记 calendar 来源。"""
    task_urls = {
        "followup": reverse("web_patient:daily_survey"),
        "checkup": reverse("web_patient:record_checkup"),
    }
    for definition in get_monitoring_definitions():
        if not definition.record_route_name:
            continue
        args = [definition.record_route_slug] if definition.record_route_slug else None
        task_urls[definition.home_type] = (
            f"{reverse(definition.record_route_name, args=args)}?source=calendar"
        )
    return task_urls


@auto_wechat_login
@check_patient
def health_calendar(request: HttpRequest) -> HttpResponse:
    """
    【页面说明】患者端健康日历 `/p/health_calendar/`
    """
    patient = request.patient

    # 1. 获取日期参数，默认为今天
    date_str = request.GET.get("date")
    if date_str:
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
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

    # 3. 获取该日期的具体指标数据（用于回显数值）
    daily_metrics = _query_calendar_metrics(
        patient.id,
        target_date,
        summary_list,
    )

    metric_plan_cache = request.session.get("metric_plan_cache") or {}
    cached_plans = metric_plan_cache.get(target_date.strftime("%Y-%m-%d")) or {}

    # 4. 构建视图数据
    daily_plans = []
    for item in summary_list:
        title_val = item.get("title") or ""
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
        
        definition = None
        if not skip_metric_query:
            definition = resolve_monitoring_definition(
                metric_type=item.get("metric_type"),
                title=title_val,
            )
        if definition and not definition.show_in_home_list:
            continue

        if (
            task_type_val == core_choices.PlanItemCategory.CHECKUP
            or "复查" in title_val
        ):
            plan_data.update(
                {
                    "type": "checkup",
                    "subtitle": "已完成" if is_completed else "未完成",
                    "action_text": "去完成",
                }
            )
        elif (
            task_type_val == core_choices.PlanItemCategory.QUESTIONNAIRE
            or "随访" in title_val
            or "问卷" in title_val
        ):
            q_ids = item.get("questionnaire_ids", [])
            action_url = reverse("web_patient:daily_survey")
            if q_ids:
                ids_str = ",".join(map(str, q_ids))
                action_url = f"{action_url}?ids={ids_str}&source=calendar"
            plan_data.update(
                {
                    "type": "followup",
                    "subtitle": "已完成" if is_completed else "未完成",
                    "action_text": "去完成",
                    "url": action_url,
                }
            )
        elif "用药" in title_val:
            plan_data.update(
                {
                    "type": "medication",
                    "subtitle": "您还未服药" if not is_completed else "已服药",
                    "action_text": "去服药",
                }
            )
        elif definition:
            plan_type = definition.home_type
            if plan_type == "bp_hr":
                existing_bp_hr = next(
                    (
                        plan
                        for plan in daily_plans
                        if plan["type"] == "bp_hr"
                    ),
                    None,
                )
                if existing_bp_hr:
                    if is_completed:
                        existing_bp_hr["status"] = "completed"
                    continue
                title = "血压/心率监测"
            else:
                title = (
                    definition.monitoring_name
                    if definition.metric_type in NEW_GENERAL_MONITORING_TYPES
                    else title_val
                )
            plan_data.update(
                {
                    "type": plan_type,
                    "title": title,
                    "subtitle": CALENDAR_MONITORING_SUBTITLES.get(
                        plan_type,
                        definition.home_subtitle.replace("今日", ""),
                    ),
                    "action_text": "去填写",
                }
            )
        else:
            continue

        if skip_metric_query:
            plan_data["status"] = (
                "completed"
                if status_val == core_choices.TaskStatus.COMPLETED
                else "pending"
            )
            if plan_data["type"] == "checkup":
                plan_data["subtitle"] = (
                    "已完成" if plan_data["status"] == "completed" else "未完成"
                )
            if plan_data["type"] == "followup":
                plan_data["subtitle"] = (
                    "已完成" if plan_data["status"] == "completed" else "未完成"
                )
        else:
            cached_plan = cached_plans.get(plan_data["type"]) if cached_plans else None
            if cached_plan:
                cached_status = cached_plan.get("status")
                if (
                    cached_status == "completed"
                    and plan_data["status"] != "completed"
                ):
                    plan_data["status"] = "completed"
                    cached_subtitle = cached_plan.get("subtitle")
                    if cached_subtitle:
                        plan_data["subtitle"] = cached_subtitle

        # 指定日期已有真实记录时，以记录为准提升完成状态并显示数值。
        plan_type = plan_data["type"]
        display_value = _format_calendar_metric_value(
            plan_type,
            definition,
            daily_metrics,
        )
        if display_value:
            plan_data["status"] = "completed"
            plan_data["subtitle"] = f"已记录：{display_value}"

        daily_plans.append(plan_data)

    # 血压/心率任务以当日血压+心率双项数据齐全才算完成；
    # 单项录入仅新增数据，不驱动计划完成（后置统一覆盖各提升路径）。
    bp_metric = daily_metrics.get(MetricType.BLOOD_PRESSURE)
    hr_metric = daily_metrics.get(MetricType.HEART_RATE)
    for plan in daily_plans:
        if plan.get("type") == "bp_hr":
            plan["status"] = "completed" if (bp_metric and hr_metric) else "pending"

    # 排序
    daily_plans.sort(
        key=lambda item: CALENDAR_PLAN_SORT_ORDER.get(item.get("type"), 999)
    )

    # URL 映射 (用于跳转)
    task_url_mapping = _build_calendar_task_urls()

    context = {
        "patient": patient,
        "target_date": target_date,
        "daily_plans": daily_plans,
        "menuUrl": task_url_mapping,
        "today": timezone.localdate(),  # 用于前端判断是否是今天
        "action_enabled": action_enabled,
    }

    # AJAX 请求返回局部模板
    if (
        request.headers.get("x-requested-with") == "XMLHttpRequest"
        or request.GET.get("ajax")
    ):
        return render(request, "web_patient/partials/_daily_plan_list.html", context)

    return render(request, "web_patient/health_calendar.html", context)
