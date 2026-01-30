from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from users.models import PatientRelation
from django.http import HttpResponseBadRequest
from users.decorators import auto_wechat_login, check_patient
from wx.services.oauth import generate_menu_auth_url




@auto_wechat_login
@check_patient
def patient_dashboard(request: HttpRequest) -> HttpResponse:
    """
    【页面说明】患者端工作台 `/p/dashboard/`。
    【模板】`web_patient/dashboard.html`，根据本人或家属身份展示功能入口与卡片。
    """
    
    
    patient = request.patient
    
    is_family = True
    is_member = bool(getattr(patient, "is_member", False) and getattr(patient, "membership_expire_date", None))

    
    # 不是家属，也不是患者， 转向填写信息
    if not patient:
        onboarding_url = reverse("web_patient:onboarding")
        return redirect(onboarding_url)

    if patient.user_id == request.user.id:
        is_family = False
    

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
            "url": reverse("web_patient:my_examination"),
        },
        {
            "title": "我的用药",
            "bg": "bg-blue-100",
            "text": "text-blue-600",
            "path": "M7 5h10v14H7z",
            "url": reverse("web_patient:my_medication"),
        },
        {
            "title": "健康档案",
            "bg": "bg-teal-100",
            "text": "text-teal-600",
            "path": "M4 6h16v12H4z",
            "url": reverse("web_patient:health_records"),
        },
    ]

    buy_url = generate_menu_auth_url("market:product_buy")
    service_entries = [
        {"title": "我的订单", "url": generate_menu_auth_url("web_patient:orders")},
        {"title": "智能设备", "url": generate_menu_auth_url("web_patient:device_list")},
        {"title": "工作室", "url": generate_menu_auth_url("web_patient:my_studio")},
        {"title": "上传报告", "url": generate_menu_auth_url("web_patient:report_list")},
        # {"title": "提醒设置", "url": "#"},
        {"title": "亲情账号", "url": generate_menu_auth_url("web_patient:family_management")},
        {"title": "健康日历", "url": generate_menu_auth_url("web_patient:health_calendar")},
        # {"title": "设置", "url": "#"},
        {"title": "意见反馈", "url": generate_menu_auth_url("web_patient:feedback")},
    ]

    return render(
        request,
        "web_patient/dashboard.html",
        {
            "patient": patient,
            "is_family": is_family,
            "is_member": is_member,
            "main_entries": main_entries,
            "service_entries": service_entries,
            "buy_url": buy_url,
        },
    )



@auto_wechat_login
@check_patient
def onboarding(request: HttpRequest) -> HttpResponse:
    """
    【页面说明】患者 onboarding 引导页 `/p/onboarding/`。
    【模板】`web_patient/onboarding.html`，用于引导首访或无档案用户完善资料。
    """
    context = {}
    if not request.user.is_authenticated:
        context["session_invalid"] = True
    return render(request, "web_patient/onboarding.html", context)
