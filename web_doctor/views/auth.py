"""
认证与账号相关视图：
- 登录 / 退出
- 医生修改密码
"""

from django.contrib import messages
from django.contrib.auth import logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from users import choices
from users.decorators import check_doctor_or_assistant
from users.services.auth import AuthService

from ..forms import DoctorPasswordChangeForm


def login_view(request: HttpRequest) -> HttpResponse:
    """登录入口：根据 user_type 跳转医生工作台或销售后台。"""
    if request.method == "POST":
        phone = request.POST.get("phone", "").strip()
        password = request.POST.get("password", "")
        success, payload = AuthService().pc_login(request, phone, password)
        if success:
            user = payload
            if user.user_type in {choices.UserType.DOCTOR, choices.UserType.ASSISTANT}:
                # 移动端适配：若是医生且使用移动设备访问，跳转至移动端首页
                user_agent = request.META.get("HTTP_USER_AGENT", "").lower()
                mobile_keywords = ["mobile", "android", "iphone", "ipad"]
                if user.user_type == choices.UserType.DOCTOR and any(k in user_agent for k in mobile_keywords):
                    return redirect("web_doctor:mobile_home")

                # 医生/医助：进入医生端工作台
                return redirect("web_doctor:doctor_workspace")
            if user.user_type == choices.UserType.SALES:
                # 销售：进入销售端 Dashboard
                return redirect("web_sales:sales_dashboard")
            # 其它角色：不允许登录医生端
            logout(request)
            messages.error(request, "当前账号无医生/销售权限")
        else:
            messages.error(request, payload)
    return render(request, "login.html")


def logout_view(request: HttpRequest) -> HttpResponse:
    """退出登录：清理 session 并返回登录页。"""
    logout(request)
    return redirect("web_doctor:login")


@login_required
@check_doctor_or_assistant
def doctor_change_password(request: HttpRequest) -> HttpResponse:
    """医生端修改密码页面：校验旧密码并更新账号密码。"""
    if request.method == "POST":
        form = DoctorPasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            messages.success(request, "密码修改成功")
            return redirect("web_doctor:doctor_workspace")
        messages.error(request, "请检查输入是否正确")
    else:
        form = DoctorPasswordChangeForm(request.user)

    return render(
        request,
        "web_doctor/change_password.html",
        {
            "form": form,
        },
    )


