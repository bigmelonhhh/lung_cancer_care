from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from users.decorators import check_patient, require_membership


@login_required
@check_patient
@require_membership
def my_studio(request: HttpRequest) -> HttpResponse:
    patient = request.patient
    studio = None
    if patient and patient.doctor:
        studio = getattr(patient.doctor, "studio", None)

    return render(
        request,
        "web_patient/studio_detail.html",
        {
            "patient": patient,
            "studio": studio,
        },
    )
