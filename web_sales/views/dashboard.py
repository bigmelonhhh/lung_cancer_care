"""销售端 Dashboard 视图。"""

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render

from users.decorators import check_sales
from users.services.sales import SalesService


@login_required
@check_sales
def sales_dashboard(request: HttpRequest) -> HttpResponse:
    """销售端 Dashboard：展示医生/患者列表及统计卡片。"""

    sales_profile = getattr(request.user, "sales_profile", None)
    if sales_profile is None:
        raise Http404("当前账号未绑定销售档案")

    doctors = list(
        sales_profile.doctors.select_related("studio").order_by("name")
    )
    patients = list(
        sales_profile.patients.select_related("doctor").order_by("-created_at")
    )

    stats = {
        "doctor_total": len(doctors),
        "patient_total": len(patients),
    }

    try:
        qrcode_url = SalesService.get_sales_qrcode_url(sales_profile)
    except Exception:
        qrcode_url = ""

    context = {
        "sales": sales_profile,
        "doctors": doctors,
        "patients": patients,
        "stats": stats,
        "qrcode_url": qrcode_url,
    }
    if request.headers.get("HX-Request") == "true":
        return render(request, "web_sales/partials/dashboard_home.html", context)

    template_name = "web_sales/dashboard.html"
    if request.COOKIES.get("ws_is_mobile") == "1":
        template_name = "web_sales/dashboard.mobile.html"
    return render(request, template_name, context)
