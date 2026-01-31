import logging
from datetime import date, datetime
from typing import Any

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import render
from django.utils import timezone

from health_data.services.medical_history_service import MedicalHistoryService
from market.service.order import get_paid_orders_for_patient
from users.decorators import check_doctor_or_assistant
from users.services.patient import PatientService
from web_doctor.views.workspace import _get_workspace_patients

logger = logging.getLogger(__name__)


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


def _format_ymd(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        return timezone.localtime(value).date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    try:
        return str(value)
    except Exception:
        return ""


@login_required
@check_doctor_or_assistant
def mobile_patient_basic_info(request: HttpRequest) -> HttpResponse:
    patient, patient_id_int = _get_patient_from_query(request)
    if patient is None:
        return HttpResponseBadRequest("参数错误")

    context = {
        "patient": patient,
        "patient_no": f"P{patient.id:06d}",
    }
    return render(request, "web_doctor/mobile/patient_basic_info.html", context)


@login_required
@check_doctor_or_assistant
def api_mobile_patient_profile(request: HttpRequest) -> JsonResponse:
    patient, patient_id_int = _get_patient_from_query(request)
    if patient_id_int is None:
        return JsonResponse({"success": False, "message": "参数错误"}, status=400)
    if patient is None:
        return JsonResponse({"success": False, "message": "未找到患者"}, status=404)

    try:
        relations_qs = PatientService().get_patient_family_members(patient)
        relations_data = []
        for rel in relations_qs:
            relations_data.append(
                {
                    "name": rel.relation_name,
                    "relation": rel.get_relation_type_display(),
                    "phone": rel.phone,
                }
            )

        patient_info = {
            "name": patient.name,
            "gender": patient.get_gender_display(),
            "phone": patient.phone,
            "birth_date": str(patient.birth_date) if getattr(patient, "birth_date", None) else "请填写出生日期",
            "address": getattr(patient, "address", "") or "",
            "emergency_contact": getattr(patient, "ec_name", "") or "",
            "emergency_relation": getattr(patient, "ec_relation", "") or "",
            "emergency_phone": getattr(patient, "ec_phone", "") or "",
            "relations": relations_data,
        }
    except Exception:
        logger.exception("加载患者基本信息失败 patient_id=%s", patient_id_int)
        return JsonResponse({"success": False, "message": "数据加载失败，请重试"}, status=500)

    return JsonResponse({"success": True, "patient_info": patient_info})


@login_required
@check_doctor_or_assistant
def api_mobile_medical_info(request: HttpRequest) -> JsonResponse:
    patient, patient_id_int = _get_patient_from_query(request)
    if patient_id_int is None:
        return JsonResponse({"success": False, "message": "参数错误"}, status=400)
    if patient is None:
        return JsonResponse({"success": False, "message": "未找到患者"}, status=404)

    try:
        last_history = MedicalHistoryService.get_last_medical_history(patient)
        if last_history:
            medical_info = {
                "diagnosis": last_history.tumor_diagnosis if last_history.tumor_diagnosis is not None else "",
                "risk_factors": last_history.risk_factors if last_history.risk_factors is not None else "",
                "clinical_diagnosis": last_history.clinical_diagnosis if last_history.clinical_diagnosis is not None else "",
                "gene_test": last_history.genetic_test if last_history.genetic_test is not None else "",
                "history": last_history.past_medical_history if last_history.past_medical_history is not None else "",
                "surgery": last_history.surgical_information if last_history.surgical_information is not None else "",
                "last_updated": last_history.created_at.strftime("%Y-%m-%d") if last_history.created_at else "",
            }
        else:
            medical_info = {
                "diagnosis": "",
                "risk_factors": "",
                "clinical_diagnosis": "",
                "gene_test": "",
                "history": "",
                "surgery": "",
                "last_updated": "",
            }

    except Exception:
        logger.exception("加载患者病情信息失败 patient_id=%s", patient_id_int)
        return JsonResponse({"success": False, "message": "数据加载失败，请重试"}, status=500)

    return JsonResponse({"success": True, "medical_info": medical_info})


@login_required
@check_doctor_or_assistant
def api_mobile_member_info(request: HttpRequest) -> JsonResponse:
    patient, patient_id_int = _get_patient_from_query(request)
    if patient_id_int is None:
        return JsonResponse({"success": False, "message": "参数错误"}, status=400)
    if patient is None:
        return JsonResponse({"success": False, "message": "未找到患者"}, status=404)

    try:
        registered_date = _format_ymd(getattr(patient, "created_at", None))

        orders = get_paid_orders_for_patient(patient)
        member_type = "付费" if orders else "普通"

        package_start_date = ""
        package_end_date = ""
        if orders:
            today = timezone.localdate()
            active_order = None
            for order in orders:
                start = getattr(order, "start_date", None)
                end = getattr(order, "end_date", None)
                if start and end and start <= today <= end:
                    active_order = order
                    break
            selected_order = active_order or orders[0]
            package_start_date = _format_ymd(getattr(selected_order, "start_date", None))
            package_end_date = _format_ymd(getattr(selected_order, "end_date", None))

        member_info = {
            "registered_date": registered_date,
            "member_type": member_type,
            "package_start_date": package_start_date,
            "package_end_date": package_end_date,
        }
    except Exception:
        logger.exception("加载患者会员信息失败 patient_id=%s", patient_id_int)
        return JsonResponse({"success": False, "message": "数据加载失败，请重试"}, status=500)

    return JsonResponse({"success": True, "member_info": member_info})
