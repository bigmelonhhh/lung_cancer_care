import logging
import calendar
import json
from datetime import datetime, timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Max, Q
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from core.models import DailyTask, Questionnaire, QuestionnaireCode
from core.models.choices import PlanItemCategory, TaskStatus
from health_data.models import HealthMetric, MetricType, ReportImage
from health_data.services.health_metric import HealthMetricService
from health_data.services.questionnaire_submission import QuestionnaireSubmissionService
from market.service.order import get_paid_orders_for_patient
from patient_alerts.services.todo_list import TodoListService
from users.decorators import check_doctor_or_assistant
from web_doctor.views.workspace import _get_workspace_patients
from wx.services.oauth import generate_menu_auth_url

from core.service.checkup import get_active_checkup_library


def _is_member(patient) -> bool:
    return bool(
        getattr(patient, "is_member", False)
        and getattr(patient, "membership_expire_date", None)
    )


QUESTIONNAIRE_RECORD_TYPE_MAP = {
    "physical": QuestionnaireCode.Q_PHYSICAL,
    "breath": QuestionnaireCode.Q_BREATH,
    "cough": QuestionnaireCode.Q_COUGH,
    "appetite": QuestionnaireCode.Q_APPETITE,
    "pain": QuestionnaireCode.Q_PAIN,
    "sleep": QuestionnaireCode.Q_SLEEP,
    "psych": QuestionnaireCode.Q_PSYCH,
    "anxiety": QuestionnaireCode.Q_ANXIETY,
    "oral_mucosa": QuestionnaireCode.Q_KQNMLB,
}

RECORD_TYPE_METRIC_MAP = {
    "medical": MetricType.USE_MEDICATED,
    "temperature": MetricType.BODY_TEMPERATURE,
    "bp": MetricType.BLOOD_PRESSURE,
    "spo2": MetricType.BLOOD_OXYGEN,
    "weight": MetricType.WEIGHT,
    "step": MetricType.STEPS,
    "heart": MetricType.HEART_RATE,
    **QUESTIONNAIRE_RECORD_TYPE_MAP,
}

QUESTIONNAIRE_RECORD_TYPES = set(QUESTIONNAIRE_RECORD_TYPE_MAP.keys())
RECORD_BATCH_SIZE = 6
WEEKDAY_MAP = {
    0: "星期一",
    1: "星期二",
    2: "星期三",
    3: "星期四",
    4: "星期五",
    5: "星期六",
    6: "星期日",
}


def _get_patient_from_query(request: HttpRequest):
    patient_id = request.GET.get("patient_id")
    try:
        patient_id_int = int(patient_id) if patient_id else None
    except (TypeError, ValueError):
        patient_id_int = None
    if not patient_id_int:
        return None, patient_id_int

    patients_qs = _get_workspace_patients(request.user, query=None).select_related("user")
    patient = patients_qs.filter(pk=patient_id_int).first()
    return patient, patient_id_int


@login_required
@check_doctor_or_assistant
def health_records(request: HttpRequest) -> HttpResponse:
    patient, patient_id_int = _get_patient_from_query(request)
    if patient is None:
        return HttpResponseBadRequest("参数错误")

    patient_id = patient.id or None
    is_member = _is_member(patient)
    selected_package_id = request.GET.get("package_id")
    entry_source = request.GET.get("source")
    entry_view = request.GET.get("view")
    is_medication_detail_entry = bool(
        entry_source == "medication" and (entry_view == "detail" or not entry_view)
    )

    service_packages = []
    if is_member:
        orders = get_paid_orders_for_patient(patient)
        for order in orders:
            service_packages.append(
                {
                    "id": order.id,
                    "name": order.product.name if getattr(order, "product_id", None) else "",
                    "start_date": order.start_date,
                    "end_date": order.end_date,
                    "is_active": False,
                }
            )

    selected_package = None
    if service_packages:
        if selected_package_id:
            try:
                selected_id_int = int(selected_package_id)
            except (TypeError, ValueError):
                selected_id_int = None
            if selected_id_int:
                selected_package = next(
                    (pkg for pkg in service_packages if pkg["id"] == selected_id_int), None
                )

        if not selected_package:
            selected_package = service_packages[0]

        for pkg in service_packages:
            if pkg["id"] == selected_package["id"]:
                pkg["is_active"] = True
                break

    today = timezone.localdate()
    if selected_package and selected_package.get("start_date") and selected_package.get("end_date"):
        start_date = selected_package["start_date"]
        end_date = selected_package["end_date"]
    else:
        start_date = datetime(2000, 1, 1).date()
        end_date = today

    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date, datetime.max.time())

    health_stats = [
        {
            "type": "medical",
            "title": "用药",
            "count": 0,
            "abnormal": 0,
            "icon": "medical",
        },
        {
            "type": "temperature",
            "title": "体温",
            "count": 0,
            "abnormal": 0,
            "icon": "temperature",
        },
        {"type": "spo2", "title": "血氧", "count": 0, "abnormal": 0, "icon": "spo2"},
        {"type": "bp", "title": "血压", "count": 0, "abnormal": 0, "icon": "bp"},
        {
            "type": "weight",
            "title": "体重",
            "count": 0,
            "abnormal": 0,
            "icon": "weight",
        },
        {"type": "heart", "title": "心率", "count": 0, "abnormal": 0, "icon": "heart"},
        {"type": "step", "title": "步数", "count": 0, "abnormal": 0, "icon": "step"},
    ]

    if patient_id:
        metric_type_map = {
            "medical": MetricType.USE_MEDICATED,
            "temperature": MetricType.BODY_TEMPERATURE,
            "spo2": MetricType.BLOOD_OXYGEN,
            "bp": MetricType.BLOOD_PRESSURE,
            "weight": MetricType.WEIGHT,
            "heart": MetricType.HEART_RATE,
            "step": MetricType.STEPS,
        }

        for item in health_stats:
            m_type = metric_type_map.get(item["type"])
            if m_type:
                try:
                    page_obj = HealthMetricService.query_metrics_by_type(
                        patient_id=int(patient_id),
                        metric_type=m_type,
                        page=1,
                        page_size=1,
                        start_date=start_dt,
                        end_date=end_dt,
                    )
                    item["count"] = page_obj.paginator.count

                    item["abnormal"] = TodoListService.count_abnormal_events(
                        patient=patient,
                        start_date=start_date,
                        end_date=end_date,
                        type=m_type,
                    )
                except Exception as e:
                    logging.error(f"查询健康指标统计失败 type={item['type']}: {e}")

    health_survey_stats = []
    checkup_stats = []
    if is_member:
        health_survey_stats = [
            {
                "type": "physical",
                "title": "体能评估",
                "count": 0,
                "abnormal": 0,
                "icon": "physical",
            },
            {
                "type": "breath",
                "title": "呼吸评估",
                "count": 0,
                "abnormal": 0,
                "icon": "breath",
            },
            {
                "type": "cough",
                "title": "咳嗽与痰色评估",
                "count": 0,
                "abnormal": 0,
                "icon": "cough",
            },
            {
                "type": "appetite",
                "title": "食欲评估",
                "count": 0,
                "abnormal": 0,
                "icon": "appetite",
            },
            {
                "type": "pain",
                "title": "身体疼痛评估",
                "count": 0,
                "abnormal": 0,
                "icon": "pain",
            },
            {
                "type": "sleep",
                "title": "睡眠质量评估",
                "count": 0,
                "abnormal": 0,
                "icon": "sleep",
            },
            {
                "type": "psych",
                "title": "抑郁评估",
                "count": 0,
                "abnormal": 0,
                "icon": "psych",
            },
            {
                "type": "anxiety",
                "title": "焦虑评估",
                "count": 0,
                "abnormal": 0,
                "icon": "anxiety",
            },
            {
                "type": "oral_mucosa",
                "title": "口腔黏膜损伤自评量表",
                "count": 0,
                "abnormal": 0,
                "icon": "oral_mucosa",
            },
        ]

        metric_type_map = {
            "physical": QuestionnaireCode.Q_PHYSICAL,
            "breath": QuestionnaireCode.Q_BREATH,
            "cough": QuestionnaireCode.Q_COUGH,
            "appetite": QuestionnaireCode.Q_APPETITE,
            "pain": QuestionnaireCode.Q_PAIN,
            "sleep": QuestionnaireCode.Q_SLEEP,
            "psych": QuestionnaireCode.Q_PSYCH,
            "anxiety": QuestionnaireCode.Q_ANXIETY,
            "oral_mucosa": QuestionnaireCode.Q_KQNMLB,
        }

        for item in health_survey_stats:
            m_type = metric_type_map.get(item["type"])
            if m_type:
                try:
                    page_obj = HealthMetricService.query_metrics_by_type(
                        patient_id=int(patient_id),
                        metric_type=m_type,
                        page=1,
                        page_size=1,
                        start_date=start_dt,
                        end_date=end_dt,
                    )
                    item["count"] = page_obj.paginator.count

                    item["abnormal"] = TodoListService.count_abnormal_events(
                        patient=patient,
                        start_date=start_date,
                        end_date=end_date,
                        type_code=m_type,
                    )
                except Exception as e:
                    logging.error(f"查询随访问卷统计失败 type={item['type']}: {e}")

        from health_data.services.report_service import ReportUploadService

        library = get_active_checkup_library()
        for lib_item in library:
            code = lib_item.get("code") or ""
            title_ = lib_item.get("name") or ""
            count_ = 0
            try:
                payload = ReportUploadService.list_report_images(
                    patient_id=int(patient_id),
                    category_code=code,
                    report_month="",
                    page_num=1,
                    page_size=1,
                    start_date=start_date,
                    end_date=end_date,
                )
                count_ = int(payload.get("total") or 0)
            except Exception as e:
                logging.error(f"查询复查档案统计失败 code={code}: {e}")
                count_ = 0
            checkup_stats.append({"code": code, "title": title_, "count": count_})

    context = {
        "patient_id": patient_id,
        "is_member": is_member,
        "service_packages": service_packages,
        "selected_package_id": selected_package["id"] if selected_package else None,
        "selected_date_range": {"start_date": start_date, "end_date": end_date},
        "health_stats": health_stats,
        "checkup_stats": checkup_stats,
        "health_survey_stats": health_survey_stats,
        "is_medication_detail_entry": is_medication_detail_entry,
    }
    return render(request, "web_doctor/mobile/health_records.html", context)


def _resolve_month_window(current_month: str) -> tuple[str, datetime, datetime, int]:
    """解析月份窗口，返回规范化月份、月起始、下月起始、当月天数。"""
    try:
        month_start = datetime.strptime(current_month, "%Y-%m")
    except ValueError:
        month_start = timezone.localtime(timezone.now()).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        current_month = month_start.strftime("%Y-%m")

    if month_start.month == 12:
        month_end_exclusive = month_start.replace(year=month_start.year + 1, month=1)
    else:
        month_end_exclusive = month_start.replace(month=month_start.month + 1)

    days_in_month = calendar.monthrange(month_start.year, month_start.month)[1]
    return current_month, month_start, month_end_exclusive, days_in_month


def _shift_month(current_month: str, step: int = -1) -> str:
    normalized_month, month_start, _, _ = _resolve_month_window(current_month)
    month_index = month_start.year * 12 + month_start.month - 1 + step
    year = month_index // 12
    month = month_index % 12 + 1
    if month < 1:
        month += 12
        year -= 1
    return f"{year:04d}-{month:02d}"


def _month_gte(left: str, right: str) -> bool:
    left_month, _, _, _ = _resolve_month_window(left)
    right_month, _, _, _ = _resolve_month_window(right)
    return left_month >= right_month


def _build_metric_record(
    *,
    metric,
    record_type: str,
    title: str,
    is_questionnaire_type: bool,
    can_operate: bool,
) -> dict:
    dt = metric.measured_at.astimezone(timezone.get_current_timezone())
    data_fields = []
    if record_type == "temperature":
        data_fields.append(
            {
                "label": "体温",
                "value": metric.display_value,
                "is_large": True,
                "key": "temperature",
            }
        )
    elif record_type == "weight":
        data_fields.append(
            {
                "label": "体重",
                "value": metric.display_value,
                "is_large": True,
                "key": "weight",
            }
        )
    elif record_type == "spo2":
        data_fields.append(
            {
                "label": "血氧",
                "value": metric.display_value,
                "is_large": True,
                "key": "spo2",
            }
        )
    elif record_type == "bp":
        data_fields = [
            {
                "label": "收缩压",
                "value": str(int(metric.value_main)),
                "is_large": True,
                "key": "ssy",
            },
            {
                "label": "舒张压",
                "value": str(int(metric.value_sub or 0)),
                "is_large": True,
                "key": "szy",
            },
        ]
    elif record_type == "medical":
        data_fields = [
            {
                "label": "用药",
                "value": "",
                "is_large": True,
                "key": "medicated",
            }
        ]
    else:
        data_fields.append(
            {
                "label": f"{title}（评分）",
                "value": metric.display_value,
                "is_large": True,
                "key": "common",
            }
        )

    return {
        "id": metric.id,
        "date": dt.strftime("%Y-%m-%d"),
        "weekday": WEEKDAY_MAP[dt.weekday()],
        "time": dt.strftime("%H:%M"),
        "source": metric.source,
        "source_display": "手动填写" if metric.source == "manual" else "设备上传",
        "is_manual": metric.source == "manual",
        "can_edit": metric.source == "manual" and dt.date() == timezone.localdate(),
        "can_operate": can_operate,
        "questionnaire_submission_id": (
            metric.questionnaire_submission_id if is_questionnaire_type else None
        ),
        "data": data_fields,
    }


def _build_review_record(*, task, title: str, can_operate: bool) -> dict:
    if task.status == TaskStatus.COMPLETED:
        status_label = "已完成"
    elif task.status == TaskStatus.TERMINATED:
        status_label = "已中止"
    elif task.status == TaskStatus.NOT_STARTED or task.task_date > timezone.localdate():
        status_label = "未开始"
    else:
        status_label = "未完成"

    time_str = "--:--"
    if task.completed_at:
        time_str = timezone.localtime(task.completed_at).strftime("%H:%M")

    return {
        "id": task.id,
        "date": task.task_date.strftime("%Y-%m-%d"),
        "weekday": WEEKDAY_MAP[task.task_date.weekday()],
        "time": time_str,
        "source": "checkup_task",
        "source_display": status_label,
        "is_manual": False,
        "can_edit": False,
        "can_operate": can_operate,
        "data": [
            {
                "label": "复查",
                "value": title,
                "is_large": True,
                "key": "checkup_name",
            },
            {
                "label": "状态",
                "value": status_label,
                "is_large": True,
                "key": "checkup_status",
            },
        ],
    }


def _load_metric_records_batch(
    *,
    patient_id: int,
    metric_type,
    record_type: str,
    title: str,
    cursor_month: str,
    cursor_offset: int,
    limit: int,
    is_questionnaire_type: bool,
    can_operate: bool,
) -> tuple[list[dict], bool, str | None, int | None]:
    earliest_metric = (
        HealthMetric.objects.filter(patient_id=patient_id, metric_type=metric_type)
        .order_by("measured_at", "id")
        .only("measured_at")
        .first()
    )
    if earliest_metric is None:
        return [], False, None, None

    earliest_month = timezone.localtime(earliest_metric.measured_at).strftime("%Y-%m")
    active_month = _resolve_month_window(cursor_month)[0]
    active_offset = max(0, cursor_offset)
    records = []
    tz = timezone.get_current_timezone()

    while len(records) < limit and _month_gte(active_month, earliest_month):
        month_label, month_start, month_end_exclusive, _ = _resolve_month_window(active_month)
        start_date = (
            timezone.make_aware(month_start, tz) if timezone.is_naive(month_start) else month_start
        )
        end_date_exclusive = (
            timezone.make_aware(month_end_exclusive, tz)
            if timezone.is_naive(month_end_exclusive)
            else month_end_exclusive
        )
        end_date_inclusive = end_date_exclusive - timedelta(microseconds=1)
        month_qs = (
            HealthMetric.objects.filter(
                patient_id=patient_id,
                metric_type=metric_type,
                measured_at__gte=start_date,
                measured_at__lte=end_date_inclusive,
            )
            .order_by("-measured_at", "-id")
        )
        month_total = month_qs.count()
        if active_offset >= month_total:
            active_month = _shift_month(month_label)
            active_offset = 0
            continue

        remaining = limit - len(records)
        month_items = list(month_qs[active_offset : active_offset + remaining])
        for metric in month_items:
            records.append(
                _build_metric_record(
                    metric=metric,
                    record_type=record_type,
                    title=title,
                    is_questionnaire_type=is_questionnaire_type,
                    can_operate=can_operate,
                )
            )

        next_offset = active_offset + len(month_items)
        if next_offset < month_total:
            return records, True, month_label, next_offset

        active_month = _shift_month(month_label)
        active_offset = 0

    has_more = bool(records) and _month_gte(active_month, earliest_month)
    return records, has_more, active_month if has_more else None, 0 if has_more else None


def _load_review_records_batch(
    *,
    patient,
    checkup_id: int,
    title: str,
    cursor_month: str,
    cursor_offset: int,
    limit: int,
    can_operate: bool,
) -> tuple[list[dict], bool, str | None, int | None]:
    earliest_task = (
        DailyTask.objects.filter(
            patient=patient,
            task_type=PlanItemCategory.CHECKUP,
            interaction_payload__checkup_id=checkup_id,
        )
        .order_by("task_date", "id")
        .only("task_date")
        .first()
    )
    if earliest_task is None:
        return [], False, None, None

    earliest_month = earliest_task.task_date.strftime("%Y-%m")
    active_month = _resolve_month_window(cursor_month)[0]
    active_offset = max(0, cursor_offset)
    records = []

    while len(records) < limit and _month_gte(active_month, earliest_month):
        month_label, month_start, month_end_exclusive, _ = _resolve_month_window(active_month)
        month_qs = (
            DailyTask.objects.filter(
                patient=patient,
                task_type=PlanItemCategory.CHECKUP,
                task_date__gte=month_start.date(),
                task_date__lt=month_end_exclusive.date(),
                interaction_payload__checkup_id=checkup_id,
            )
            .order_by("-task_date", "-id")
        )
        month_total = month_qs.count()
        if active_offset >= month_total:
            active_month = _shift_month(month_label)
            active_offset = 0
            continue

        remaining = limit - len(records)
        month_items = list(month_qs[active_offset : active_offset + remaining])
        for task in month_items:
            records.append(
                _build_review_record(
                    task=task,
                    title=title,
                    can_operate=can_operate,
                )
            )

        next_offset = active_offset + len(month_items)
        if next_offset < month_total:
            return records, True, month_label, next_offset

        active_month = _shift_month(month_label)
        active_offset = 0

    has_more = bool(records) and _month_gte(active_month, earliest_month)
    return records, has_more, active_month if has_more else None, 0 if has_more else None


def _load_review_image_groups_batch(
    *,
    patient_id: int,
    category_code: str,
    cursor_month: str,
    cursor_offset: int,
    limit: int,
) -> tuple[list[dict], bool, str | None, int | None]:
    if not patient_id or not category_code:
        return [], False, None, None

    base_qs = (
        ReportImage.objects.filter(
            upload__patient_id=patient_id,
            record_type=ReportImage.RecordType.CHECKUP,
            checkup_item__code=str(category_code),
            upload__deleted_at__isnull=True,
        )
        .exclude(report_date__isnull=True)
    )

    earliest_report_date = (
        base_qs.order_by("report_date", "id").values_list("report_date", flat=True).first()
    )
    if earliest_report_date is None:
        return [], False, None, None

    earliest_month = earliest_report_date.strftime("%Y-%m")
    active_month = _resolve_month_window(cursor_month)[0]
    active_offset = max(0, cursor_offset)
    groups = []

    while len(groups) < limit and _month_gte(active_month, earliest_month):
        month_label, month_start, month_end_exclusive, _ = _resolve_month_window(active_month)
        month_date_qs = (
            base_qs.filter(
                report_date__gte=month_start.date(),
                report_date__lt=month_end_exclusive.date(),
            )
            .values("report_date")
            .annotate(max_id=Max("id"))
            .order_by("-report_date", "-max_id")
        )
        month_total = month_date_qs.count()
        if active_offset >= month_total:
            active_month = _shift_month(month_label)
            active_offset = 0
            continue

        remaining = limit - len(groups)
        month_rows = list(month_date_qs[active_offset : active_offset + remaining])
        date_list = [row["report_date"] for row in month_rows]
        if date_list:
            images_qs = (
                base_qs.filter(report_date__in=date_list)
                .values("report_date", "image_url")
                .order_by("-report_date", "-id")
            )
            images_by_date = {report_date: [] for report_date in date_list}
            for row in images_qs:
                images_by_date.setdefault(row["report_date"], []).append(row["image_url"])

            for report_date in date_list:
                groups.append(
                    {
                        "report_date": report_date.strftime("%Y-%m-%d"),
                        "image_urls": images_by_date.get(report_date, []),
                    }
                )

        next_offset = active_offset + len(date_list)
        if next_offset < month_total:
            return groups, True, month_label, next_offset

        active_month = _shift_month(month_label)
        active_offset = 0

    has_more = bool(groups) and _month_gte(active_month, earliest_month)
    return groups, has_more, active_month if has_more else None, 0 if has_more else None


def _build_medication_chart_payload(
    *,
    patient,
    month_start_date,
    month_end_exclusive_date,
    month_days,
) -> dict:
    task_map = {}
    task_qs = DailyTask.objects.filter(
        patient=patient,
        task_type=PlanItemCategory.MEDICATION,
        task_date__gte=month_start_date,
        task_date__lt=month_end_exclusive_date,
    ).only("task_date", "status")

    for task in task_qs:
        task_map.setdefault(task.task_date, []).append(task.status)

    items = []
    for day in month_days:
        statuses = task_map.get(day) or []
        if not statuses:
            status = "none"
        elif all(status_val == TaskStatus.COMPLETED for status_val in statuses):
            status = "completed"
        else:
            status = "pending"

        items.append(
            {
                "full_date": day.strftime("%Y-%m-%d"),
                "date": day.strftime("%m-%d"),
                "status": status,
            }
        )

    return {"items": items}


def _build_line_chart_payload(
    *,
    patient_id: int,
    metric_type: str,
    record_type: str,
    title: str,
    start_date: datetime,
    end_date_exclusive: datetime,
    month_days,
) -> dict:
    color_map = {
        "temperature": "#ef4444",
        "weight": "#06b6d4",
        "spo2": "#3b82f6",
        "heart": "#f97316",
        "step": "#22c55e",
        "bp": "#2563eb",
        "oral_mucosa": "#ef4444",
    }
    day_set = set(month_days)
    latest_map = {}
    questionnaire_task_dates = set()

    if record_type in QUESTIONNAIRE_RECORD_TYPES and month_days:
        questionnaire_code = QUESTIONNAIRE_RECORD_TYPE_MAP.get(record_type)
        questionnaire_id = (
            Questionnaire.objects.filter(code=questionnaire_code)
            .values_list("id", flat=True)
            .first()
        )
        task_filters = Q(interaction_payload__questionnaire_code=questionnaire_code)
        if questionnaire_id:
            task_filters = task_filters | Q(plan_item__template_id=questionnaire_id)

        questionnaire_task_dates = set(
            DailyTask.objects.filter(
                patient_id=patient_id,
                task_type=PlanItemCategory.QUESTIONNAIRE,
                task_date__gte=month_days[0],
                task_date__lt=end_date_exclusive.date(),
            )
            .filter(task_filters)
            .values_list("task_date", flat=True)
        )

    metrics = (
        HealthMetric.objects.filter(
            patient_id=patient_id,
            metric_type=metric_type,
            measured_at__gte=start_date,
            measured_at__lt=end_date_exclusive,
        )
        .order_by("measured_at", "id")
        .only("measured_at", "value_main", "value_sub")
    )

    for metric in metrics:
        local_dt = timezone.localtime(metric.measured_at)
        local_day = local_dt.date()
        if local_day not in day_set:
            continue

        if record_type == "bp":
            latest_map[local_day] = {
                "ssy": int(metric.value_main) if metric.value_main is not None else None,
                "szy": int(metric.value_sub) if metric.value_sub is not None else None,
            }
        elif metric.value_main is not None:
            if record_type in {"temperature", "weight"}:
                latest_map[local_day] = float(metric.value_main)
            elif record_type in {"spo2", "heart", "step"}:
                latest_map[local_day] = int(metric.value_main)
            else:
                latest_map[local_day] = float(metric.value_main)

    dates = [day.strftime("%m-%d") for day in month_days]
    full_dates = [day.strftime("%Y-%m-%d") for day in month_days]

    if record_type == "bp":
        ssy_data = []
        szy_data = []
        for day in month_days:
            day_values = latest_map.get(day)
            ssy_data.append(day_values.get("ssy") if day_values else 0)
            szy_data.append(day_values.get("szy") if day_values else 0)

        return {
            "dates": dates,
            "full_dates": full_dates,
            "series": [
                {"name": "收缩压", "data": ssy_data, "color": "#ef4444"},
                {"name": "舒张压", "data": szy_data, "color": "#2563eb"},
            ],
        }

    if record_type in QUESTIONNAIRE_RECORD_TYPES:
        series_data = []
        for day in month_days:
            has_task = day in questionnaire_task_dates
            day_score = latest_map.get(day)
            if not has_task:
                series_data.append(
                    {
                        "value": 0,
                        "raw_value": None,
                        "is_no_task": True,
                    }
                )
                continue

            normalized_score = day_score if day_score is not None else 0
            series_data.append(
                {
                    "value": normalized_score,
                    "raw_value": normalized_score,
                    "is_no_task": False,
                }
            )

        return {
            "dates": dates,
            "full_dates": full_dates,
            "series": [
                {
                    "name": title,
                    "data": series_data,
                    "color": color_map.get(record_type, "#3b82f6"),
                }
            ],
        }

    series_data = [latest_map.get(day, 0) for day in month_days]
    return {
        "dates": dates,
        "full_dates": full_dates,
        "series": [
            {
                "name": title,
                "data": series_data,
                "color": color_map.get(record_type, "#3b82f6"),
            }
        ],
    }


@login_required
@check_doctor_or_assistant
def health_record_detail(request: HttpRequest) -> HttpResponse:
    record_type = request.GET.get("type")
    title = request.GET.get("title", "历史记录")
    checkup_id = request.GET.get("checkup_id")
    source = request.GET.get("source")
    view = request.GET.get("view")
    is_medication_detail_view = bool(record_type == "medical" and view == "detail")
    is_questionnaire_type = bool(record_type in QUESTIONNAIRE_RECORD_TYPES)

    patient, patient_id_int = _get_patient_from_query(request)
    if patient is None:
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse(
                {
                    "records": [],
                    "has_more": False,
                    "next_cursor_month": None,
                    "next_cursor_offset": None,
                    "batch_size": RECORD_BATCH_SIZE,
                },
                status=400,
            )
        return HttpResponseBadRequest("参数错误")

    patient_id = patient.id or None
    is_member = _is_member(patient)

    general_record_types = {
        "medical",
        "temperature",
        "bp",
        "spo2",
        "weight",
        "step",
        "heart",
        "bp_hr",
    }
    show_operation_controls = bool(
        source == "health_records" and record_type in general_record_types
    )
    show_add_button = False
    if record_type == "medical":
        show_operation_controls = False

    member_only_types = {
        "review_record",
        "physical",
        "breath",
        "cough",
        "appetite",
        "pain",
        "sleep",
        "psych",
        "anxiety",
        "oral_mucosa",
    }
    if record_type in member_only_types and not is_member:
        buy_url = generate_menu_auth_url("market:product_buy")
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse(
                {"success": False, "message": "该功能为会员专属，请先开通会员", "buy_url": buy_url},
                status=403,
            )
        return redirect(buy_url)

    chart_record_types = {
        "medical",
        "temperature",
        "bp",
        "spo2",
        "weight",
        "step",
        "heart",
        "bp_hr",
        "physical",
        "breath",
        "cough",
        "appetite",
        "pain",
        "sleep",
        "psych",
        "anxiety",
        "oral_mucosa",
    }

    current_month = request.GET.get("month", datetime.now().strftime("%Y-%m"))
    current_month, month_start, month_end_exclusive, days_in_month = _resolve_month_window(
        current_month
    )
    cursor_month = request.GET.get("cursor_month") or current_month

    tz = timezone.get_current_timezone()
    start_date = (
        timezone.make_aware(month_start, tz) if timezone.is_naive(month_start) else month_start
    )
    end_date_exclusive = (
        timezone.make_aware(month_end_exclusive, tz)
        if timezone.is_naive(month_end_exclusive)
        else month_end_exclusive
    )
    # HealthMetricService.query_metrics_by_type 使用 <= 结束时间，这里转成“下月起始前1微秒”避免跨月误纳入
    end_date_inclusive = end_date_exclusive - timedelta(microseconds=1)
    month_start_date = month_start.date()
    month_end_exclusive_date = month_end_exclusive.date()
    month_days = [month_start_date + timedelta(days=i) for i in range(days_in_month)]

    try:
        cursor_offset = max(0, int(request.GET.get("cursor_offset", 0)))
    except (TypeError, ValueError):
        cursor_offset = 0

    limit_raw = request.GET.get("limit")
    is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"
    default_limit = days_in_month if is_ajax else RECORD_BATCH_SIZE
    if limit_raw is None:
        limit = default_limit
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            limit = default_limit
    limit = max(1, min(limit, days_in_month))

    chart_available = bool(record_type in chart_record_types)
    chart_mode = "medication_table" if record_type == "medical" else "line"
    chart_payload = {"items": []} if chart_mode == "medication_table" else {"dates": [], "series": []}
    chart_canvas_width = max(days_in_month * 48, 640)

    records = []
    has_more = False
    next_cursor_month = None
    next_cursor_offset = None
    checkup_id_int = None

    if patient_id and record_type:
        try:
            if record_type == "review_record":
                try:
                    checkup_id_int = int(checkup_id) if checkup_id else None
                except (TypeError, ValueError):
                    checkup_id_int = None

                if checkup_id_int:
                    (
                        records,
                        has_more,
                        next_cursor_month,
                        next_cursor_offset,
                    ) = _load_review_records_batch(
                        patient=patient,
                        checkup_id=checkup_id_int,
                        title=title,
                        cursor_month=cursor_month,
                        cursor_offset=cursor_offset,
                        limit=limit,
                        can_operate=not is_medication_detail_view,
                    )
            else:
                db_metric_type = RECORD_TYPE_METRIC_MAP.get(record_type)

                if db_metric_type:
                    (
                        records,
                        has_more,
                        next_cursor_month,
                        next_cursor_offset,
                    ) = _load_metric_records_batch(
                        patient_id=int(patient_id),
                        metric_type=db_metric_type,
                        record_type=record_type,
                        title=title,
                        cursor_month=cursor_month,
                        cursor_offset=cursor_offset,
                        limit=limit,
                        is_questionnaire_type=is_questionnaire_type,
                        can_operate=not is_medication_detail_view,
                    )

                    if chart_available:
                        if record_type == "medical":
                            chart_payload = _build_medication_chart_payload(
                                patient=patient,
                                month_start_date=month_start_date,
                                month_end_exclusive_date=month_end_exclusive_date,
                                month_days=month_days,
                            )
                        else:
                            chart_payload = _build_line_chart_payload(
                                patient_id=int(patient_id),
                                metric_type=db_metric_type,
                                record_type=record_type,
                                title=title,
                                start_date=start_date,
                                end_date_exclusive=end_date_exclusive,
                                month_days=month_days,
                            )

        except Exception:
            logging.exception("查询详情失败")
            records = []
            has_more = False
            next_cursor_month = None
            next_cursor_offset = None
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse(
                    {
                        "records": [],
                        "has_more": False,
                        "next_cursor_month": None,
                        "next_cursor_offset": None,
                        "batch_size": limit,
                    },
                    status=500,
                )

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse(
            {
                "records": records,
                "has_more": has_more,
                "next_cursor_month": next_cursor_month,
                "next_cursor_offset": next_cursor_offset,
                "batch_size": limit,
            }
        )

    context = {
        "record_type": record_type,
        "is_questionnaire_type": is_questionnaire_type,
        "title": title,
        "records": records,
        "has_records": bool(records),
        "current_month": current_month,
        "patient_id": patient_id,
        "has_more": has_more,
        "next_cursor_month": next_cursor_month,
        "next_cursor_offset": next_cursor_offset,
        "batch_size": limit,
        "checkup_id": checkup_id_int if checkup_id_int else checkup_id,
        "source": source,
        "show_operation_controls": show_operation_controls,
        "show_add_button": show_add_button,
        "days_in_month": days_in_month,
        "chart_mode": chart_mode,
        "chart_available": chart_available,
        "chart_payload": chart_payload,
        "chart_payload_json": json.dumps(chart_payload, ensure_ascii=False),
        "chart_canvas_width": chart_canvas_width,
    }

    return render(request, "web_doctor/mobile/health_record_detail.html", context)


@login_required
@check_doctor_or_assistant
def mobile_questionnaire_submission_detail(
    request: HttpRequest, submission_id: int
) -> HttpResponse:
    patient, _ = _get_patient_from_query(request)
    next_url = request.GET.get("next") or ""

    fallback_url = reverse("web_doctor:mobile_patient_list")
    if patient and patient.id:
        fallback_url = (
            f"{reverse('web_doctor:mobile_health_records')}"
            f"?patient_id={patient.id}"
        )

    redirect_target = fallback_url
    if next_url and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        redirect_target = next_url

    if patient is None:
        return redirect(redirect_target)

    detail = QuestionnaireSubmissionService.get_submission_detail_for_patient(
        submission_id=submission_id,
        patient_id=patient.id,
    )
    if not detail:
        return redirect(redirect_target)

    context = {
        "title": f"{detail.get('questionnaire_name') or '问卷'}答题详情",
        "questionnaire_name": detail.get("questionnaire_name") or "问卷",
        "submission_id": detail.get("submission_id"),
        "submitted_at": detail.get("submitted_at"),
        "questions": detail.get("questions") or [],
        "next_url": redirect_target,
        "patient_id": patient.id,
    }
    return render(request, "web_doctor/mobile/questionnaire_submission_detail.html", context)


@login_required
@check_doctor_or_assistant
def review_record_detail(request: HttpRequest) -> HttpResponse:
    patient, patient_id_int = _get_patient_from_query(request)
    if patient is None:
        return HttpResponseBadRequest("参数错误")

    category_code = request.GET.get("category_code") or ""
    title = request.GET.get("title", "复查档案")
    patient_id = patient.id or None
    current_month = request.GET.get("month") or timezone.localdate().strftime("%Y-%m")
    current_month, _, _, _ = _resolve_month_window(current_month)
    initial_groups = []
    has_more = False
    next_cursor_month = None
    next_cursor_offset = None

    if patient_id and category_code:
        (
            initial_groups,
            has_more,
            next_cursor_month,
            next_cursor_offset,
        ) = _load_review_image_groups_batch(
            patient_id=int(patient_id),
            category_code=category_code,
            cursor_month=current_month,
            cursor_offset=0,
            limit=RECORD_BATCH_SIZE,
        )

    context = {
        "patient_id": patient_id,
        "title": title,
        "category_code": category_code,
        "current_month": current_month,
        "initial_groups": initial_groups,
        "has_more": has_more,
        "next_cursor_month": next_cursor_month,
        "next_cursor_offset": next_cursor_offset,
        "batch_size": RECORD_BATCH_SIZE,
    }
    return render(request, "web_doctor/mobile/review_record_detail.html", context)


@login_required
@check_doctor_or_assistant
def review_record_detail_data(request: HttpRequest) -> JsonResponse:
    from django.core.exceptions import ValidationError
    from health_data.services.report_service import ReportUploadService

    patient, patient_id_int = _get_patient_from_query(request)
    if patient is None:
        return JsonResponse({"success": False, "message": "参数错误"}, status=400)

    category_code = request.GET.get("category_code") or ""
    use_cursor_pagination = any(
        key in request.GET for key in ("month", "cursor_month", "cursor_offset", "limit")
    )

    if use_cursor_pagination:
        if not category_code:
            return JsonResponse({"success": False, "message": "category_code 不能为空。"}, status=400)

        current_month = request.GET.get("month") or timezone.localdate().strftime("%Y-%m")
        current_month, _, _, _ = _resolve_month_window(current_month)
        cursor_month = request.GET.get("cursor_month") or current_month
        try:
            cursor_offset = max(0, int(request.GET.get("cursor_offset", 0)))
        except (TypeError, ValueError):
            return JsonResponse({"success": False, "message": "cursor_offset 必须为整数。"}, status=400)

        try:
            limit = int(request.GET.get("limit", RECORD_BATCH_SIZE))
        except (TypeError, ValueError):
            return JsonResponse({"success": False, "message": "limit 必须为整数。"}, status=400)
        limit = max(1, limit)

        try:
            (
                groups,
                has_more,
                next_cursor_month,
                next_cursor_offset,
            ) = _load_review_image_groups_batch(
                patient_id=int(patient.id) if patient.id else 0,
                category_code=category_code,
                cursor_month=cursor_month,
                cursor_offset=cursor_offset,
                limit=limit,
            )
        except Exception:
            logging.exception("查询复查详情失败")
            return JsonResponse({"success": False, "message": "数据加载失败，请重试"}, status=500)

        return JsonResponse(
            {
                "success": True,
                "list": groups,
                "has_more": has_more,
                "next_cursor_month": next_cursor_month,
                "next_cursor_offset": next_cursor_offset,
                "batch_size": limit,
            }
        )

    report_month = request.GET.get("report_month") or timezone.localdate().strftime("%Y-%m")
    page_num = request.GET.get("page_num", 1)
    page_size = request.GET.get("page_size", 10)

    try:
        payload = ReportUploadService.list_report_images(
            patient_id=int(patient.id) if patient.id else 0,
            category_code=category_code,
            report_month=report_month,
            page_num=page_num,
            page_size=page_size,
        )
    except ValidationError as e:
        message = "参数错误"
        if getattr(e, "messages", None):
            message = e.messages[0]
        return JsonResponse({"success": False, "message": message}, status=400)
    except Exception:
        logging.exception("查询复查详情失败")
        return JsonResponse({"success": False, "message": "数据加载失败，请重试"}, status=500)

    return JsonResponse({"success": True, **payload})
