"""销售端患者录入视图。"""

import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import models
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.dateparse import parse_date

from users import choices
from users.decorators import check_sales
from users.services.patient import PatientService
from regions.models import Province
from users.models import PatientProfile


@login_required
@check_sales
def patient_entry(request: HttpRequest) -> HttpResponse:
    """销售端患者档案录入。"""

    if request.method == "POST":
        birth_date = parse_date(request.POST.get("birth_date", ""))
        try:
            gender_value = int(request.POST.get("gender", choices.Gender.MALE))
        except (TypeError, ValueError):
            gender_value = choices.Gender.MALE

        data = {
            "name": request.POST.get("name", "").strip(),
            "gender": gender_value,
            "birth_date": birth_date,
            "phone": request.POST.get("phone", "").strip(),
            "address_detail": request.POST.get("address_detail", "").strip(),
            "province_id": request.POST.get("address_province"),
            "city_id": request.POST.get("address_city"),
            "ec_name": request.POST.get("ec_name", "").strip(),
            "ec_relation": request.POST.get("ec_relation", "").strip(),
            "ec_phone": request.POST.get("ec_phone", "").strip(),
            "diagnosis": request.POST.get("diagnosis", "").strip(),
            "pathology": request.POST.get("pathology", "").strip(),
            "tnm_stage": request.POST.get("tnm_stage", "").strip(),
            "gene_mutation": request.POST.get("gene_mutation", "").strip(),
            "surgery_info": request.POST.get("surgery_info", "").strip(),
            "doctor_note": request.POST.get("doctor_note", "").strip(),
            "risk_factors": request.POST.getlist("risk_factors"),
        }

        try:
            PatientService().create_full_patient_record(request.user, data)
        except ValidationError as exc:
            messages.error(request, exc.message)
        else:
            messages.success(request, "患者档案录入成功")
            return redirect("web_sales:sales_dashboard")

    risk_options = ["家族遗传", "吸烟", "职业暴露", "空气污染", "肺部慢病", "其它"]
    provinces = Province.objects.all().order_by("name")

    return render(
        request,
        "web_sales/patient_entry.html",
        {
            "gender_choices": choices.Gender.choices,
            "risk_options": risk_options,
            "provinces": provinces,
        },
    )


@login_required
@check_sales
def check_patient_phone(request: HttpRequest) -> HttpResponse:
    """手机号查重并返回 OOB 回填片段。"""

    phone = request.GET.get("phone", "").strip()
    patient = None
    sales_profile = getattr(request.user, "sales_profile", None)
    if phone and sales_profile:
        patient = (
            PatientProfile.objects.select_related("sales")
            .filter(phone=phone)
            .filter(models.Q(sales=sales_profile) | models.Q(sales__isnull=True))
            .first()
        )

    patient_data = {}
    risk_factors = []
    if patient:
        latest_history = (
            patient.medical_histories.order_by("-created_at").first()
        )
        if latest_history:
            risk_factors = [
                tag.strip()
                for tag in (latest_history.risk_factors or "").split(",")
                if tag.strip()
            ]
        patient_data = {
            "name": patient.name or "",
            "gender": patient.gender,
            "birth_date": patient.birth_date.strftime("%Y-%m-%d")
            if patient.birth_date
            else "",
            "phone": patient.phone,
            "address": patient.address or "",
            "ec_name": patient.ec_name or "",
            "ec_relation": patient.ec_relation or "",
            "ec_phone": patient.ec_phone or "",
            "diagnosis": latest_history.diagnosis if latest_history else "",
            "pathology": latest_history.pathology if latest_history else "",
            "tnm_stage": latest_history.tnm_stage if latest_history else "",
            "gene_mutation": latest_history.gene_mutation if latest_history else "",
            "surgery_info": latest_history.surgery_info if latest_history else "",
            "doctor_note": latest_history.doctor_note if latest_history else "",
        }
    else:
        patient_data = {
            "name": "",
            "gender": choices.Gender.MALE,
            "birth_date": "",
            "phone": phone,
            "address": "",
            "ec_name": "",
            "ec_relation": "",
            "ec_phone": "",
            "diagnosis": "",
            "pathology": "",
            "tnm_stage": "",
            "gene_mutation": "",
            "surgery_info": "",
            "doctor_note": "",
        }

    risk_options = [
        "家族遗传",
        "吸烟",
        "职业暴露",
        "空气污染",
        "肺部慢病",
        "其它",
    ]

    return render(
        request,
        "web_sales/partials/phone_autofill.html",
        {
            "has_patient": bool(patient),
            "patient_data": patient_data,
            "gender_choices": choices.Gender.choices,
            "risk_options": risk_options,
            "risk_factors": risk_factors,
        },
    )
