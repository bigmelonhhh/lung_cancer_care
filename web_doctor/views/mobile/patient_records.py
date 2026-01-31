from django.http import Http404, HttpRequest, HttpResponse
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from users.decorators import check_doctor_or_assistant

from web_doctor.views.reports_history_data import get_reports_page_for_patient
from web_doctor.views.workspace import _get_workspace_patients


@login_required
@check_doctor_or_assistant
def mobile_patient_records(request: HttpRequest, patient_id: int) -> HttpResponse:
    patients_qs = _get_workspace_patients(request.user, query=None).select_related("user")
    patient = patients_qs.filter(pk=patient_id).first()
    if patient is None:
        raise Http404("未找到患者")

    reports_page = get_reports_page_for_patient(request, patient, page_size=10)
    context = {
        "patient": patient,
        "patient_no": f"P{patient.id:06d}",
        "reports_page": reports_page,
    }
    return render(request, "web_doctor/mobile/patient_records.html", context)

