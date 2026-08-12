from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.core.paginator import Paginator

from users.decorators import check_doctor_or_assistant

from web_doctor.views.workspace import (
    _attach_patients_affiliation_info,
    _attach_patients_service_status_codes,
    _get_workspace_patients,
    _split_patients_by_service_status,
    enrich_patients_with_counts,
)


@login_required
@check_doctor_or_assistant
def mobile_patient_list(request: HttpRequest) -> HttpResponse:
    query = request.GET.get("q") or ""
    managed_page_number = request.GET.get("managed_page") or "1"
    stopped_page_number = request.GET.get("stopped_page") or "1"
    unpaid_page_number = request.GET.get("unpaid_page") or "1"

    patients_qs = _get_workspace_patients(request.user, query)
    patients = list(patients_qs)
    _attach_patients_service_status_codes(patients)

    # 对齐 PC 端：按服务状态拆为 管理中(active) / 停止管理(expired) / 未付费(none) 三组。
    managed_patients, stopped_patients, unpaid_patients = _split_patients_by_service_status(patients)

    managed_paginator = Paginator(managed_patients, 30)
    stopped_paginator = Paginator(stopped_patients, 30)
    unpaid_paginator = Paginator(unpaid_patients, 30)
    managed_page = managed_paginator.get_page(managed_page_number)
    stopped_page = stopped_paginator.get_page(stopped_page_number)
    unpaid_page = unpaid_paginator.get_page(unpaid_page_number)

    # 仅对每组当前页富集待办/咨询计数，保持移动端现有性能特征。
    managed_items = enrich_patients_with_counts(request.user, managed_page.object_list)
    stopped_items = enrich_patients_with_counts(request.user, stopped_page.object_list)
    unpaid_items = enrich_patients_with_counts(request.user, unpaid_page.object_list)
    _attach_patients_affiliation_info(managed_items + stopped_items + unpaid_items)

    context = {
        "q": query,
        "managed_total": managed_paginator.count,
        "stopped_total": stopped_paginator.count,
        "unpaid_total": unpaid_paginator.count,
        "managed_page": managed_page,
        "stopped_page": stopped_page,
        "unpaid_page": unpaid_page,
        "managed_patients": managed_items,
        "stopped_patients": stopped_items,
        "unpaid_patients": unpaid_items,
    }
    return render(request, "web_doctor/mobile/patient_list.html", context)
