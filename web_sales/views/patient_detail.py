"""患者详情视图，供销售端 HTMX 加载。"""

import logging

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from users.decorators import check_sales
from users.models import PatientProfile
from users.services.patient import PatientService

logger = logging.getLogger(__name__)


@login_required
@check_sales
def patient_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """返回患者详情局部模板。"""

    sales_profile = getattr(request.user, "sales_profile", None)
    if not sales_profile:
        raise Http404("未找到销售档案")

    patient = (
        PatientProfile.objects.select_related("sales", "doctor")
        .filter(pk=pk, sales=sales_profile)
        .first()
    )
    if patient is None:
        raise Http404("患者不存在或无权查看")

    qrcode_url = None
    try:
        qrcode_url = PatientService().generate_bind_qrcode(patient.pk)
    except ValidationError as exc:
        logger.warning("生成患者二维码失败：%s", exc)
    except Exception:  # pragma: no cover - 网络/微信异常
        logger.exception("生成患者二维码异常")

    doctors = sales_profile.doctors.order_by("name")

    return render(
        request,
        "web_sales/partials/detail_card.html",
        {
            "patient": patient,
            "qrcode_url": qrcode_url,
            "doctors": doctors,
        },
    )


@login_required
@check_sales
@require_POST
def update_patient_doctor(request: HttpRequest, pk: int) -> HttpResponse:
    """更新患者主治医生。"""

    sales_profile = getattr(request.user, "sales_profile", None)
    if not sales_profile:
        raise Http404("未找到销售档案")

    patient = (
        PatientProfile.objects.select_related("sales")
        .filter(pk=pk, sales=sales_profile)
        .first()
    )
    if patient is None:
        raise Http404("患者不存在或无权查看")

    doctor_id = request.POST.get("doctor_id")
    doctor = None
    if doctor_id:
        doctor = sales_profile.doctors.filter(pk=doctor_id).first()
        if doctor is None:
            raise Http404("医生不存在或无权绑定")

    patient.doctor = doctor
    patient.save(update_fields=["doctor", "updated_at"])

    return render(
        request,
        "web_sales/partials/doctor_update_toast.html",
        {
            "doctor": doctor,
        },
    )
