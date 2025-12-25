from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from users.decorators import check_patient
from users.models import PatientProfile, PatientRelation
from users.services.patient import PatientService
from web_patient.forms import PatientSelfEntryForm


def _get_primary_patient(request: HttpRequest) -> PatientProfile:
    patient = request.patient
    if patient:
        return patient

    raise Http404("未找到患者档案")


def _get_patient_for_request(request: HttpRequest, patient_id: int) -> PatientProfile:
    patient = (
        PatientProfile.objects.select_related("doctor", "sales")
        .filter(pk=patient_id)
        .first()
    )
    if patient is None:
        raise Http404("患者档案不存在")

    owned_profile = getattr(request.user, "patient_profile", None)
    if owned_profile and owned_profile.pk == patient.pk:
        return patient

    has_relation = (
        PatientRelation.objects.filter(
            user=request.user, patient_id=patient_id, is_active=True
        )
        .only("id")
        .exists()
    )
    if has_relation:
        return patient

    raise Http404("无权访问该档案")


def _hx_flag(request: HttpRequest) -> bool:
    return bool(request.headers.get("HX-Request"))


@login_required
@check_patient
def profile_page(request: HttpRequest) -> HttpResponse:
    patient = request.patient
    return render(
        request,
        "web_patient/profile_info.html",
        {
            "patient": patient,
        },
    )


@login_required
@check_patient
def profile_card(request: HttpRequest, patient_id: int) -> HttpResponse:
    patient = request.patient
    return render(
        request,
        "web_patient/partials/profile_card.html",
        {"patient": patient, "is_hx_request": _hx_flag(request)},
    )


@login_required
@check_patient
def profile_edit_form(request: HttpRequest, patient_id: int) -> HttpResponse:
    patient = request.patient
    form = PatientSelfEntryForm(instance=patient)
    return render(
        request,
        "web_patient/partials/profile_form.html",
        {
            "patient": patient,
            "form": form,
            "gender_value": form["gender"].value(),
            "is_hx_request": _hx_flag(request),
        },
    )


@login_required
@check_patient
@require_POST
def profile_update(request: HttpRequest, patient_id: int) -> HttpResponse:
    patient = request.patient
    form = PatientSelfEntryForm(request.POST, instance=patient)
    
    if form.is_valid():
        
        try:
            updated_patient = PatientService().save_patient_profile(
                request.user,
                form.cleaned_data,
                profile_id=patient.id,
            )
        except ValidationError as exc:
            
            form.add_error(None, exc.message)
        else:
            messages.success(request, "个人资料已更新")
            return render(
                request,
                "web_patient/partials/profile_card.html",
                {
                    "patient": updated_patient,
                    "is_hx_request": _hx_flag(request),
                },
            )

    return render(
        request,
        "web_patient/partials/profile_form.html",
        {
            "patient": patient,
            "form": form,
            "gender_value": form["gender"].value(),
            "is_hx_request": _hx_flag(request),
        },
        status=400,
    )
