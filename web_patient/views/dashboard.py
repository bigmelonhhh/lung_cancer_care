from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from users.models import PatientRelation


@login_required
def patient_dashboard(request: HttpRequest) -> HttpResponse:
    """患者端首页：根据本人或家属身份展示档案。"""

    patient = getattr(request.user, "patient_profile", None)
    is_family = False

    if patient is None:
        relation = (
            PatientRelation.objects.select_related("patient")
            .filter(user=request.user)
            .order_by("-created_at")
            .first()
        )
        if relation and relation.patient:
            patient = relation.patient
            is_family = True

    if patient is None:
        onboarding_url = reverse("web_patient:onboarding")
        return redirect(onboarding_url)

    main_entries = [
        {
            "title": "我的随访",
            "bg": "bg-yellow-100",
            "text": "text-yellow-600",
            "path": "M9 5l7 7-7 7",
        },
        {
            "title": "我的复查",
            "bg": "bg-purple-100",
            "text": "text-purple-600",
            "path": "M5 12h14M12 5l7 7-7 7",
        },
        {
            "title": "我的用药",
            "bg": "bg-blue-100",
            "text": "text-blue-600",
            "path": "M7 5h10v14H7z",
        },
        {
            "title": "健康档案",
            "bg": "bg-teal-100",
            "text": "text-teal-600",
            "path": "M4 6h16v12H4z",
        },
    ]
    service_entries = [
        ("我的订单", "M6 6h12v12H6z"),
        ("智能设备", "M10 6v12m4-12v12"),
        ("工作室", "M12 4l8 8-8 8-8-8z"),
        ("检查报告", "M6 7h12M6 12h12M6 17h8"),
        ("提醒设置", "M12 8v4l2 2"),
        ("亲情账号", "M5 17l4-4 3 3 7-7"),
        ("健康日历", "M6 10h12M6 14h12"),
        ("设置", "M12 6l1.5 3H17l-2.5 2 1 3-3.5-2-3.5 2 1-3L7 9h3.5z"),
        ("意见反馈", "M5 5h14v14H5z"),
    ]

    return render(
        request,
        "web_patient/dashboard.html",
        {
            "patient": patient,
            "is_family": is_family,
            "main_entries": main_entries,
            "service_entries": service_entries,
        },
    )


@login_required
def onboarding(request: HttpRequest) -> HttpResponse:
    """无档案用户的引导页。"""

    return render(request, "web_patient/onboarding.html")
