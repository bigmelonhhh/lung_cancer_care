from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from users.decorators import check_patient
from users.models import PatientRelation
from users.services.patient import PatientService
from wx.services.oauth import generate_menu_auth_url

patient_service = PatientService()


@login_required
@check_patient
def family_management(request: HttpRequest) -> HttpResponse:
    patient = request.patient
    if not patient:
        return redirect("web_patient:onboarding")

    family_limit = patient_service.get_family_binding_limit(patient)
    active_family_count = patient_service.get_active_family_count(patient)
    can_add_family = active_family_count < family_limit

    qrcode_url = None
    if can_add_family:
        try:
            qrcode_url = patient_service.generate_bind_qrcode(patient.pk)
        except ValidationError as exc:  # pragma: no cover - 网络异常
            messages.error(request, exc.message)

    relations = (
        PatientRelation.objects.select_related("user")
        .filter(patient=patient, is_active=True)
        .exclude(user=patient.user)
        .order_by("-created_at")
    )

    return render(
        request,
        "web_patient/family_management.html",
        {
            "patient": patient,
            "relations": relations,
            "qrcode_url": qrcode_url,
            "family_limit": family_limit,
            "can_add_family": can_add_family,
            "family_limit_message": patient_service.get_family_binding_limit_message(
                patient
            ),
        },
    )


@require_POST
@login_required
@check_patient
def unbind_family(request: HttpRequest) -> HttpResponse:
    relation_id = request.POST.get("relation_id")
    if not relation_id:
        messages.error(request, "未提供亲情账号 ID")
        return redirect(generate_menu_auth_url("web_patient:family_management"))
    try:
        relation_id = int(relation_id)
    except ValueError:
        messages.error(request, "亲情账号 ID 无效")
        return redirect(generate_menu_auth_url("web_patient:family_management"))

    try:
        patient_service.unbind_relation(request.patient, relation_id)
    except ValidationError as exc:
        messages.error(request, exc.message)
    else:
        messages.success(request, "已解绑该亲情账号")
    return redirect(generate_menu_auth_url("web_patient:family_management"))
