from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from users import choices
from users.services import AuthService, PatientService

auth_service = AuthService()
patient_service = PatientService()
from users.decorators import auto_wechat_login
from wx.services.oauth import generate_menu_auth_url


@auto_wechat_login
def bind_landing(request: HttpRequest, patient_id: int) -> HttpResponse:
    """
    【页面说明】患者绑定落地页 `/p/bind/<patient_id>/`。
    【模板】`web_patient/bind_landing.html`，用于展示患者信息和亲属关系选项。
    """

    try:
        patient = patient_service.get_profile_for_bind(patient_id)
    except ValidationError:
        raise Http404("患者档案不存在")

    family_limit = patient_service.get_family_binding_limit(patient)
    active_family_count = patient_service.get_active_family_count(patient)
    can_add_family = active_family_count < family_limit
    family_limit_message = patient_service.get_family_binding_limit_message(patient)

    family_relation_choices = [
        (value, label)
        for value, label in choices.RelationType.choices
        if value != choices.RelationType.SELF
    ]
    family_default = (
        family_relation_choices[0][0]
        if family_relation_choices
        else choices.RelationType.SPOUSE
    )

    if not request.user.is_authenticated:
        if not can_add_family:
            messages.error(
                request,
                family_limit_message,
            )
        return render(
            request,
            "web_patient/bind_landing.html",
            {
                "patient": patient,
                "family_relation_choices": family_relation_choices,
                "family_default": family_default,
                "can_add_family": can_add_family,
                "family_limit": family_limit,
                "family_limit_message": family_limit_message,
            },
        )

    already_bound = (
        patient.user_id == request.user.id
        or patient.relations.filter(user=request.user, is_active=True).exists()
    )
    if already_bound:
        return render(
            request,
            "web_patient/bind_success.html",
            {"patient": patient},
        )

    if not can_add_family:
        messages.error(
            request,
            family_limit_message,
        )

    return render(
        request,
        "web_patient/bind_landing.html",
        {
            "patient": patient,
            "family_relation_choices": family_relation_choices,
            "family_default": family_default,
            "can_add_family": can_add_family,
            "family_limit": family_limit,
            "family_limit_message": family_limit_message,
        },
    )


@require_POST
@auto_wechat_login
def bind_submit(request: HttpRequest, patient_id: int) -> HttpResponse:
    """
    【页面说明】绑定表单提交接口 `/p/bind/<patient_id>/submit/`。
    【作用】处理落地页上的亲情账号/本人绑定操作，保存后渲染成功页。
    """

    if not request.user.is_authenticated:
        messages.error(request, "请先通过微信确认身份后再绑定。")
        return redirect(reverse("web_patient:bind_landing", args=[patient_id]))

    try:
        patient = patient_service.get_profile_for_bind(patient_id)
    except ValidationError:
        raise Http404("患者档案不存在")

    try:
        relation_type = int(
            request.POST.get("relation_type", choices.RelationType.SPOUSE)
        )
    except (TypeError, ValueError):
        relation_type = choices.RelationType.SPOUSE

    relation_name = (request.POST.get("relation_name") or "").strip()
    receive_notification = request.POST.get("receive_notification") == "on"

    try:
        patient = patient_service.process_binding(
            request.user,
            patient_id,
            relation_type,
            relation_name=relation_name,
            receive_alert_msg=receive_notification,
        )
    except ValidationError as exc:
        messages.error(request, exc.message)
        return redirect(reverse("web_patient:bind_landing", args=[patient_id]))

    return render(
        request,
        "web_patient/bind_success.html",
        {
            "patient": patient,
            "url": generate_menu_auth_url("web_patient:patient_dashboard")
        },
    )
