from django.shortcuts import render
from django.http import HttpRequest, HttpResponse
from users.decorators import auto_wechat_login, check_patient
def get_patient_chat_title(patient) -> str:
    if patient and getattr(patient, "doctor", None) and getattr(patient.doctor, "studio", None):
        return patient.doctor.studio.name
    return "医患咨询"
@auto_wechat_login
@check_patient
def consultation_chat(request: HttpRequest) -> HttpResponse:
    """
    【页面说明】医患咨询聊天页面
    【模板】`web_patient/consultation_chat.html`
    """
    patient = request.patient
    patient_id = request.GET.get("patient_id") or (patient.id if patient else None)
    is_family = True
    if patient and patient.user_id == request.user.id:
        is_family = False
    
    context = {
        "patient": patient,
        "patient_id": patient_id,
        "chat_title": get_patient_chat_title(patient),
        "is_family": is_family,
    }
    return render(request, "web_patient/consultation_chat.html", context)
