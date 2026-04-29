import logging
import time

from django.core.cache import cache
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from core.models import choices as core_choices
from core.service.tasks import get_daily_plan_summary
from health_data.models import MetricType
from health_data.services.health_metric import HealthMetricService
from users.decorators import auto_wechat_login, check_patient
from users.services.patient import PatientService
from wx.services.oauth import generate_menu_auth_url

from . import chat_api

logger = logging.getLogger(__name__)

HOME_CACHE_TTL_SECONDS = 30
HOME_SUCCESS_PARAM_TASK_MAP = {
    "temperature": "temperature",
    "bp_hr": "bp_hr",
    "spo2": "spo2",
    "weight": "weight",
    "breath_val": "breath",
    "sputum_val": "sputum",
    "pain_val": "pain",
    "step": "step",
    "medication_taken": "medication",
    "checkup_completed": "checkup",
    "followup": "followup",
}

# 定义计划类型与健康指标的映射关系
PLAN_METRIC_MAPPING = {
    "step": {
        "key": MetricType.STEPS,
        "name": "步数",
        "format_func": lambda x: f"{x['value_display']}",
    },
    "体温": {
        "key": MetricType.BODY_TEMPERATURE,
        "name": "体温",
        "format_func": lambda x: f"{x['value_display']}",
    },
    "血压": {
        "key": [MetricType.BLOOD_PRESSURE, MetricType.HEART_RATE],
        "name": "血压心率",
        "format_func": lambda x: (
            f"血压{x[MetricType.BLOOD_PRESSURE]['value_display'] if x.get(MetricType.BLOOD_PRESSURE) else '--'}mmHg，"
            f"心率{x[MetricType.HEART_RATE]['value_display'] if x.get(MetricType.HEART_RATE) else '--'}"
        ),
    },
    "血氧": {
        "key": MetricType.BLOOD_OXYGEN,
        "name": "血氧饱和度",
        "format_func": lambda x: f"{x['value_display']}",
    },
    "体重": {
        "key": MetricType.WEIGHT,
        "name": "体重",
        "format_func": lambda x: f"{x['value_display']}",
    },
    "用药提醒": {
        "key": MetricType.USE_MEDICATED,
        "name": "用药提醒",
        "format_func": lambda x: "已服药" if x else "未服药",
    },
    "随访": {
        "key": "followup",
        "name": "随访",
        "format_func": lambda x: "已完成" if x else "未完成",
    },
    "复查": {
        "key": "checkup",
        "name": "复查",
        "format_func": lambda x: "已完成" if x else "未完成",
    },
}

PLAN_TYPE_METRIC_MAPPING = {
    "temperature": PLAN_METRIC_MAPPING["体温"],
    "bp_hr": PLAN_METRIC_MAPPING["血压"],
    "spo2": PLAN_METRIC_MAPPING["血氧"],
    "weight": PLAN_METRIC_MAPPING["体重"],
    "medication": PLAN_METRIC_MAPPING["用药提醒"],
    "followup": PLAN_METRIC_MAPPING["随访"],
    "checkup": PLAN_METRIC_MAPPING["复查"],
}

PLAN_SORT_ORDER = {
    "medication": 1,
    "spo2": 2,
    "bp_hr": 3,
    "weight": 4,
    "temperature": 5,
    "checkup": 6,
    "followup": 7,
}

MEASURE_PLAN_TYPES = {"temperature", "bp_hr", "spo2", "weight"}
OPTIMISTIC_COMPLETED_TASK_TYPES = MEASURE_PLAN_TYPES | {"medication"}


def _cache_key(namespace: str, patient_id: int, date_key: str, user_id: int = None) -> str:
    if user_id is None:
        return f"web_patient:home:{namespace}:{patient_id}:{date_key}"
    return f"web_patient:home:{namespace}:{patient_id}:{user_id}:{date_key}"


def _fetch_with_cache(cache_key: str, bypass_cache: bool, fetcher, perf_log: dict, perf_key: str):
    if not bypass_cache:
        cached_payload = cache.get(cache_key)
        if isinstance(cached_payload, dict) and "value" in cached_payload:
            perf_log[f"{perf_key}_cache"] = "hit"
            perf_log[f"{perf_key}_ms"] = 0.0
            return cached_payload["value"]

    start_at = time.perf_counter()
    value = fetcher()
    duration_ms = round((time.perf_counter() - start_at) * 1000, 2)

    perf_log[f"{perf_key}_cache"] = "bypass" if bypass_cache else "miss"
    perf_log[f"{perf_key}_ms"] = duration_ms

    cache.set(cache_key, {"value": value}, HOME_CACHE_TTL_SECONDS)
    return value


def _build_daily_plans(summary_list):
    daily_plans = []
    has_bp_hr_plan = False

    for item in summary_list:
        status_val = item.get("status")
        is_completed = status_val == core_choices.TaskStatus.COMPLETED
        title_val = item.get("title")

        plan_data = {
            "type": "unknown",
            "title": title_val,
            "subtitle": "请按时完成",
            "status": "completed" if is_completed else "pending",
            "action_text": "去完成",
            "icon_class": "bg-blue-100 text-blue-600",
        }

        if "步数" in title_val:
            continue

        if "用药" in title_val:
            plan_data.update(
                {
                    "type": "medication",
                    "subtitle": item.get("subtitle")
                    or ("您今天还未服药" if not is_completed else "今日已服药"),
                    "action_text": "去服药",
                }
            )
        elif "体温" in title_val:
            plan_data.update(
                {
                    "type": "temperature",
                    "subtitle": item.get("subtitle") or "请记录今日体温",
                    "action_text": "去填写",
                }
            )
        elif "血压" in title_val or "心率" in title_val:
            if has_bp_hr_plan:
                continue

            has_bp_hr_plan = True
            plan_data.update(
                {
                    "type": "bp_hr",
                    "title": "血压/心率监测",
                    "subtitle": item.get("subtitle") or "请记录今日血压心率情况",
                    "action_text": "去填写",
                }
            )
        elif "血氧" in title_val:
            plan_data.update(
                {
                    "type": "spo2",
                    "subtitle": item.get("subtitle") or "请记录今日血氧饱和度",
                    "action_text": "去填写",
                }
            )
        elif "体重" in title_val:
            plan_data.update(
                {
                    "type": "weight",
                    "subtitle": item.get("subtitle") or "请记录今日体重",
                    "action_text": "去填写",
                }
            )
        elif "随访" in title_val or "问卷" in title_val:
            q_ids = item.get("questionnaire_ids", [])
            has_pending_questionnaires = bool(q_ids)
            followup_completed = is_completed or not has_pending_questionnaires
            action_url = ""
            if q_ids:
                action_url = reverse("web_patient:daily_survey")
                ids_str = ",".join(map(str, q_ids))
                action_url = f"{action_url}?ids={ids_str}&source=home"

            plan_data.update(
                {
                    "type": "followup",
                    "status": "completed" if followup_completed else "pending",
                    "subtitle": (
                        "已完成随访任务"
                        if followup_completed
                        else (item.get("subtitle") or "请及时完成您的随访任务")
                    ),
                    "action_text": "去完成",
                    "url": action_url,
                }
            )
        elif "复查" in title_val:
            plan_data.update(
                {
                    "type": "checkup",
                    "subtitle": item.get("subtitle")
                    or ("请及时完成您的复查任务" if not is_completed else "已完成复查任务"),
                    "action_text": "去完成",
                }
            )
        else:
            continue

        daily_plans.append(plan_data)

    daily_plans.sort(key=lambda x: PLAN_SORT_ORDER.get(x.get("type"), 999))
    return daily_plans


def _get_metric_value(metric_key, data):
    if not metric_key or not data:
        return None
    if isinstance(metric_key, list):
        combined_data = {k: data.get(k) for k in metric_key}
        has_data = any(v is not None for v in combined_data.values())
        return combined_data if has_data else None
    return data.get(metric_key) if data.get(metric_key) is not None else None


def _is_today_data(metric_info: dict) -> bool:
    if not metric_info or "measured_at" not in metric_info:
        return False

    utc_time = metric_info["measured_at"]
    local_time = timezone.localtime(utc_time)
    return local_time.date() == timezone.localdate()


@auto_wechat_login
@check_patient
def patient_home(request: HttpRequest) -> HttpResponse:
    """
    【页面说明】患者端首页 `/p/home/`
    【模板】`web_patient/patient_home.html`，根据本人或家属身份展示功能入口与卡片。
    """
    patient = request.patient
    if not patient:
        onboarding_url = reverse("web_patient:onboarding")
        return redirect(onboarding_url)

    is_family = patient.user_id != request.user.id
    is_member = bool(
        getattr(patient, "is_member", False)
        and getattr(patient, "membership_expire_date", None)
    )

    patient_id = patient.id or None
    service_days = "0"
    daily_plans = []
    list_data = {}
    step_count = "0"
    baseline_steps = getattr(patient, "baseline_steps", None)
    has_baseline_steps = baseline_steps is not None
    unread_chat_count = 0

    completed_task_types = set()
    for param, task_type in HOME_SUCCESS_PARAM_TASK_MAP.items():
        if request.GET.get(param):
            completed_task_types.add(task_type)

    if request.GET.get("followup") == "true":
        completed_task_types.add("followup")

    optimistic_completed_task_types = (
        completed_task_types & OPTIMISTIC_COMPLETED_TASK_TYPES
    )
    cache_bypass = bool(completed_task_types)
    perf_log = {"cache_bypass": cache_bypass}

    if patient_id and is_member:
        try:
            served_days, _ = PatientService().get_guard_days(patient)
            service_days = served_days
        except Exception:
            logger.debug("patient_home guard_days failed patient_id=%s", patient_id)

        date_key = timezone.localdate().strftime("%Y%m%d")

        summary_cache_key = _cache_key("daily_plan_summary", int(patient_id), date_key)
        try:
            summary_list = _fetch_with_cache(
                cache_key=summary_cache_key,
                bypass_cache=cache_bypass,
                fetcher=lambda: get_daily_plan_summary(patient),
                perf_log=perf_log,
                perf_key="daily_plan_summary",
            )
        except Exception:
            logger.debug("patient_home summary fetch failed patient_id=%s", patient_id)
            summary_list = []

        daily_plans = _build_daily_plans(summary_list or [])

        metric_cache_key = _cache_key("last_metric", int(patient_id), date_key)
        try:
            list_data = _fetch_with_cache(
                cache_key=metric_cache_key,
                bypass_cache=cache_bypass,
                fetcher=lambda: HealthMetricService.query_last_metric(int(patient_id)),
                perf_log=perf_log,
                perf_key="query_last_metric",
            ) or {}
        except Exception:
            logger.debug("patient_home metric fetch failed patient_id=%s", patient_id)
            list_data = {}

        unread_cache_key = _cache_key(
            "unread_count",
            int(patient_id),
            date_key,
            user_id=request.user.id,
        )
        try:
            unread_chat_count = _fetch_with_cache(
                cache_key=unread_cache_key,
                bypass_cache=cache_bypass,
                fetcher=lambda: chat_api.get_unread_chat_count(patient, request.user),
                perf_log=perf_log,
                perf_key="get_unread_chat_count",
            ) or 0
        except Exception:
            logger.debug("patient_home unread fetch failed patient_id=%s", patient_id)
            unread_chat_count = 0

        if MetricType.STEPS in list_data and list_data[MetricType.STEPS] is not None:
            steps_info = list_data[MetricType.STEPS]
            if _is_today_data(steps_info):
                step_count = steps_info.get("value_display", "0")


    for plan in daily_plans:
        plan_type = plan.get("type")
        if not plan_type:
            continue

        metric_config = PLAN_TYPE_METRIC_MAPPING.get(plan_type)
        if not metric_config:
            continue

        metric_data = _get_metric_value(metric_config["key"], list_data)
        has_today_data = False

        if metric_data:
            metric_key = metric_config["key"]
            raw_metric_info = None
            if isinstance(metric_key, list):
                for key_item in metric_key:
                    if list_data.get(key_item):
                        raw_metric_info = list_data[key_item]
                        break
            else:
                raw_metric_info = list_data.get(metric_key)

            if _is_today_data(raw_metric_info):
                has_today_data = True
                plan["status"] = "completed"
                try:
                    display_value = metric_config["format_func"](metric_data)
                    plan["subtitle"] = f"今日已记录：{display_value}"
                except Exception:
                    plan["subtitle"] = "今日已记录"

        if not has_today_data:
            if plan_type in optimistic_completed_task_types:
                plan["status"] = "completed"
                plan["subtitle"] = "今日已记录：提交成功"
            elif plan_type in MEASURE_PLAN_TYPES:
                plan["status"] = "pending"

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
        "is_family": is_family,
        "is_member": is_member,
        "service_days": service_days,
        "daily_plans": daily_plans,
        "buy_url": generate_menu_auth_url("market:product_buy"),
        "patient_id": patient_id,
        "menuUrl": task_url_mapping,
        "step_count": step_count,
        "baseline_steps": baseline_steps,
        "has_baseline_steps": has_baseline_steps,
        "unread_chat_count": unread_chat_count,
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
