from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from business_support.service.sms import SMSService
from users.services.patient import PatientService
from web_patient.forms import PatientEntryVerificationForm
from users.decorators import check_patient

patient_service = PatientService()


@login_required
@check_patient
def patient_entry(request: HttpRequest) -> HttpResponse:
    """
    【页面说明】患者自助建档页 `/p/entry/`。
    """

    if request.method == "POST":
        form = PatientEntryVerificationForm(request.POST)
        if form.is_valid():
            try:
                patient_service.save_patient_profile(request.user, form.cleaned_data)
            except ValidationError as exc:
                form.add_error(None, exc.message)
            else:
                return redirect(reverse("web_patient:patient_dashboard"))
    else:
        initial = {}
        phone = getattr(request.user, "phone", "")
        if phone:
            initial["phone"] = phone
        form = PatientEntryVerificationForm(initial=initial)

    base_url = getattr(settings, "WEB_BASE_URL", "").rstrip("/")

    def _full_url(path: str) -> str:
        if not base_url:
            return path
        return f"{base_url}{path}"

    return render(
        request,
        "web_patient/patient_entry.html",
        {
            "form": form,
            "urls": {
                "user_policy": _full_url("/p/docs/User_Policy/"),
            },
        },
    )


@require_POST
def send_auth_code(request: HttpRequest) -> JsonResponse:
    """
    【接口说明】验证码发送接口 `/p/api/send-code/`。
    """

    phone = (request.POST.get("phone") or "").strip()
    if not phone:
        return JsonResponse({"success": False, "message": "请填写手机号"}, status=400)

    success, message = SMSService.send_verification_code(phone)
    status_code = 200 if success else 400
    return JsonResponse({"success": success, "message": message}, status=status_code)
