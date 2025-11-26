"""web_doctor 应用视图：登录、医生/销售工作台。"""

from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from users import choices
from users.services.auth import AuthService


def login_view(request: HttpRequest) -> HttpResponse:
    """登录入口，依据 user_type 跳转不同 Dashboard。"""

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        success, payload = AuthService().pc_login(request, username, password)
        if success:
            user = payload
            if user.user_type in {choices.UserType.DOCTOR, choices.UserType.ASSISTANT}:
                return redirect("web_doctor:doctor_dashboard")
            if user.user_type == choices.UserType.SALES:
                return redirect("web_doctor:sales_dashboard")
            logout(request)
            messages.error(request, "当前账号无医生/销售权限")
        else:
            messages.error(request, payload)
    return render(request, "login.html")


def logout_view(request: HttpRequest) -> HttpResponse:
    """退出登录后回到登录页。"""

    logout(request)
    return redirect("web_doctor:login")


@login_required
def doctor_dashboard(request: HttpRequest) -> HttpResponse:
    """医生端 Dashboard 占位页。"""

    return render(request, "web_doctor/doctor_index.html")


@login_required
def sales_dashboard(request: HttpRequest) -> HttpResponse:
    """销售端 Dashboard 占位页。"""

    return render(request, "web_doctor/sales_index.html")
