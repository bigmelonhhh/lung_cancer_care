from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.core.paginator import Paginator

from users.decorators import check_doctor_or_assistant

from web_doctor.views.workspace import (
    _attach_patients_service_status_codes,
    _get_workspace_patients,
    enrich_patients_with_counts,
)


@login_required
@check_doctor_or_assistant
def mobile_patient_list(request: HttpRequest) -> HttpResponse:
    query = request.GET.get("q") or ""
    managed_page_number = request.GET.get("managed_page") or "1"
    unmanaged_page_number = request.GET.get("unmanaged_page") or "1"

    patients_qs = _get_workspace_patients(request.user, query)
    patients = list(patients_qs)
    _attach_patients_service_status_codes(patients)

    managed_patients = []
    unmanaged_patients = []
    for patient in patients:
        state = getattr(patient, "service_status_code", None) or patient.service_status
        if state == "active":
            managed_patients.append(patient)
        else:
            unmanaged_patients.append(patient)

    managed_paginator = Paginator(managed_patients, 30)
    unmanaged_paginator = Paginator(unmanaged_patients, 30)
    managed_page = managed_paginator.get_page(managed_page_number)
    unmanaged_page = unmanaged_paginator.get_page(unmanaged_page_number)

    managed_items = enrich_patients_with_counts(request.user, managed_page.object_list)
    unmanaged_items = enrich_patients_with_counts(request.user, unmanaged_page.object_list)

    context = {
        "q": query,
        "managed_total": managed_paginator.count,
        "unmanaged_total": unmanaged_paginator.count,
        "managed_page": managed_page,
        "unmanaged_page": unmanaged_page,
        "managed_patients": managed_items,
        "unmanaged_patients": unmanaged_items,
    }
    return render(request, "web_doctor/mobile/patient_list.html", context)
