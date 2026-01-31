import logging
from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from core.models import DailyTask, QuestionnaireCode
from core.models.choices import PlanItemCategory, TaskStatus
from health_data.models import MetricType
from health_data.services.health_metric import HealthMetricService
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
            {"type": "pain", "title": "疼痛评估", "count": 0, "abnormal": 0, "icon": "pain"},
            {"type": "sleep", "title": "睡眠评估", "count": 0, "abnormal": 0, "icon": "sleep"},
            {"type": "psych", "title": "心理评估", "count": 0, "abnormal": 0, "icon": "psych"},
            {"type": "anxiety", "title": "焦虑评估", "count": 0, "abnormal": 0, "icon": "anxiety"},
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
                        type=m_type,
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
                    report_month=today.strftime("%Y-%m"),
                    page_num=1,
                    page_size=1,
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


@login_required
@check_doctor_or_assistant
def health_record_detail(request: HttpRequest) -> HttpResponse:
    record_type = request.GET.get("type")
    title = request.GET.get("title", "历史记录")
    checkup_id = request.GET.get("checkup_id")
    source = request.GET.get("source")
    view = request.GET.get("view")
    is_medication_detail_view = bool(record_type == "medical" and view == "detail")

    patient, patient_id_int = _get_patient_from_query(request)
    if patient is None:
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"records": [], "has_more": False, "next_page": None}, status=400)
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
    }
    if record_type in member_only_types and not is_member:
        buy_url = generate_menu_auth_url("market:product_buy")
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse(
                {"success": False, "message": "该功能为会员专属，请先开通会员", "buy_url": buy_url},
                status=403,
            )
        return redirect(buy_url)

    current_month = request.GET.get("month", datetime.now().strftime("%Y-%m"))
    try:
        start_date = datetime.strptime(current_month, "%Y-%m")
        if start_date.month == 12:
            end_date = start_date.replace(year=start_date.year + 1, month=1)
        else:
            end_date = start_date.replace(month=start_date.month + 1)
    except ValueError:
        start_date = datetime.now().replace(day=1)
        if start_date.month == 12:
            end_date = start_date.replace(year=start_date.year + 1, month=1)
        else:
            end_date = start_date.replace(month=start_date.month + 1)
        current_month = start_date.strftime("%Y-%m")

    tz = timezone.get_current_timezone()
    if timezone.is_naive(start_date):
        start_date = timezone.make_aware(start_date, tz)
    if timezone.is_naive(end_date):
        end_date = timezone.make_aware(end_date, tz)

    try:
        page = int(request.GET.get("page", 1))
        limit = int(request.GET.get("limit", 30))
    except (TypeError, ValueError):
        page = 1
        limit = 30

    records = []
    has_more = False

    if patient_id and record_type:
        try:
            if record_type == "review_record":
                try:
                    checkup_id_int = int(checkup_id) if checkup_id else None
                except (TypeError, ValueError):
                    checkup_id_int = None

                if not checkup_id_int:
                    records = []
                else:
                    month_start_date = start_date.date()
                    month_end_exclusive = end_date.date()
                    today = timezone.localdate()
                    weekday_map = {
                        0: "星期一",
                        1: "星期二",
                        2: "星期三",
                        3: "星期四",
                        4: "星期五",
                        5: "星期六",
                        6: "星期日",
                    }

                    qs = (
                        DailyTask.objects.filter(
                            patient=patient,
                            task_type=PlanItemCategory.CHECKUP,
                            task_date__gte=month_start_date,
                            task_date__lt=month_end_exclusive,
                            interaction_payload__checkup_id=checkup_id_int,
                        )
                        .order_by("-task_date", "-id")
                    )
                    paginator = Paginator(qs, limit)
                    page_obj = paginator.get_page(page)
                    has_more = page_obj.has_next()

                    for task in page_obj.object_list:
                        if task.status == TaskStatus.COMPLETED:
                            status_label = "已完成"
                        elif task.status == TaskStatus.TERMINATED:
                            status_label = "已中止"
                        elif task.status == TaskStatus.NOT_STARTED or task.task_date > today:
                            status_label = "未开始"
                        else:
                            status_label = "未完成"

                        time_str = "--:--"
                        if task.completed_at:
                            time_str = timezone.localtime(task.completed_at).strftime("%H:%M")

                        records.append(
                            {
                                "id": task.id,
                                "date": task.task_date.strftime("%Y-%m-%d"),
                                "weekday": weekday_map[task.task_date.weekday()],
                                "time": time_str,
                                "source": "checkup_task",
                                "source_display": status_label,
                                "is_manual": False,
                                "can_edit": False,
                                "can_operate": not is_medication_detail_view,
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
                        )
                if request.headers.get("x-requested-with") == "XMLHttpRequest":
                    return JsonResponse(
                        {
                            "records": records,
                            "has_more": has_more,
                            "next_page": page + 1 if has_more else None,
                        }
                    )
                context = {
                    "record_type": record_type,
                    "title": title,
                    "records": records,
                    "current_month": current_month,
                    "patient_id": patient_id,
                    "has_more": has_more,
                    "next_page": page + 1 if has_more else None,
                    "checkup_id": checkup_id_int if checkup_id else None,
                    "source": source,
                    "show_operation_controls": show_operation_controls,
                    "show_add_button": show_add_button,
                }
                return render(request, "web_doctor/mobile/health_record_detail.html", context)

            metric_type_map = {
                "medical": MetricType.USE_MEDICATED,
                "temperature": MetricType.BODY_TEMPERATURE,
                "bp": MetricType.BLOOD_PRESSURE,
                "spo2": MetricType.BLOOD_OXYGEN,
                "weight": MetricType.WEIGHT,
                "step": MetricType.STEPS,
                "heart": MetricType.HEART_RATE,
                "physical": QuestionnaireCode.Q_PHYSICAL,
                "breath": QuestionnaireCode.Q_BREATH,
                "cough": QuestionnaireCode.Q_COUGH,
                "appetite": QuestionnaireCode.Q_APPETITE,
                "pain": QuestionnaireCode.Q_PAIN,
                "sleep": QuestionnaireCode.Q_SLEEP,
                "psych": QuestionnaireCode.Q_PSYCH,
                "anxiety": QuestionnaireCode.Q_ANXIETY,
            }

            db_metric_type = metric_type_map.get(record_type)

            if db_metric_type:
                page_obj = HealthMetricService.query_metrics_by_type(
                    patient_id=int(patient_id),
                    metric_type=db_metric_type,
                    page=page,
                    page_size=limit,
                    start_date=start_date,
                    end_date=end_date,
                )

                raw_list = page_obj.object_list
                has_more = page < page_obj.paginator.num_pages
                weekday_map = {
                    0: "星期一",
                    1: "星期二",
                    2: "星期三",
                    3: "星期四",
                    4: "星期五",
                    5: "星期六",
                    6: "星期日",
                }
                for metric in raw_list:
                    dt = metric.measured_at.astimezone(timezone.get_current_timezone())
                    date_str = dt.strftime("%Y-%m-%d")
                    time_str = dt.strftime("%H:%M")

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
                                "label": title + "（评分）",
                                "value": metric.display_value,
                                "is_large": True,
                                "key": "common",
                            }
                        )

                    records.append(
                        {
                            "id": metric.id,
                            "date": date_str,
                            "weekday": weekday_map[dt.weekday()],
                            "time": time_str,
                            "source": metric.source,
                            "source_display": (
                                "手动填写" if metric.source == "manual" else "设备上传"
                            ),
                            "is_manual": metric.source == "manual",
                            "can_edit": metric.source == "manual"
                            and dt.date() == timezone.localdate(),
                            "can_operate": not is_medication_detail_view,
                            "data": data_fields,
                        }
                    )

        except Exception:
            logging.exception("查询详情失败")
            records = []
            has_more = False
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse(
                    {"records": [], "has_more": False, "next_page": None}, status=500
                )

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse(
            {
                "records": records,
                "has_more": has_more,
                "next_page": page + 1 if has_more else None,
            }
        )

    context = {
        "record_type": record_type,
        "title": title,
        "records": records,
        "current_month": current_month,
        "patient_id": patient_id,
        "has_more": has_more,
        "next_page": page + 1 if has_more else None,
        "checkup_id": checkup_id,
        "source": source,
        "show_operation_controls": show_operation_controls,
        "show_add_button": show_add_button,
    }

    return render(request, "web_doctor/mobile/health_record_detail.html", context)


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

    context = {
        "patient_id": patient_id,
        "title": title,
        "category_code": category_code,
        "current_month": current_month,
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
