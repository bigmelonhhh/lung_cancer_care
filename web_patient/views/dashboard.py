from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from users.models import PatientRelation
from django.http import HttpResponseBadRequest




def patient_dashboard(request: HttpRequest) -> HttpResponse:
    """患者端首页：根据本人或家属身份展示档案。"""
    
    #个人中心， 一定会有code这个字段进来。所以如果没有，直接报错。
    code =  request.GET.get('code')
    if not code:
        return HttpResponseBadRequest('非法请求：缺少必要的认证参数 (code)')
    
    from users.services.auth import AuthService
    auth_service = AuthService()
    auth_service.wechat_login(request, code)

    patient = getattr(request.user, "patient_profile", None)
    print(f"request.user.id is {request.user.id}")
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

    orders_url = reverse("web_patient:orders")

    main_entries = [
        {
            "title": "我的随访",
            "bg": "bg-yellow-100",
            "text": "text-yellow-600",
            "path": "M9 5l7 7-7 7",
            "url": "#",
        },
        {
            "title": "我的复查",
            "bg": "bg-purple-100",
            "text": "text-purple-600",
            "path": "M5 12h14M12 5l7 7-7 7",
            "url": "#",
        },
        {
            "title": "我的用药",
            "bg": "bg-blue-100",
            "text": "text-blue-600",
            "path": "M7 5h10v14H7z",
            "url": "#",
        },
        {
            "title": "健康档案",
            "bg": "bg-teal-100",
            "text": "text-teal-600",
            "path": "M4 6h16v12H4z",
            "url": "#",
        },
    ]
    service_entries = [
        {"title": "我的订单", "url": orders_url},
        {"title": "智能设备", "url": "#"},
        {"title": "工作室", "url": "#"},
        {"title": "检查报告", "url": "#"},
        {"title": "提醒设置", "url": "#"},
        {"title": "亲情账号", "url": "#"},
        {"title": "健康日历", "url": "#"},
        {"title": "设置", "url": "#"},
        {"title": "意见反馈", "url": "#"},
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
