from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from users import choices
from users.decorators import check_doctor_or_assistant
from users.services.assistant import list_platform_assistants_for_doctor


@login_required
@check_doctor_or_assistant
def mobile_my_assistant(request: HttpRequest) -> HttpResponse:
    if request.user.user_type == choices.UserType.ASSISTANT:
        return render(request, "web_doctor/mobile/my_assistant.html", {"assistants": []})

    doctor_profile = getattr(request.user, "doctor_profile", None)
    if doctor_profile is None:
        return render(request, "web_doctor/mobile/my_assistant.html", {"assistants": []})

    studio = doctor_profile.studio
    if studio is None:
        owned_studio = doctor_profile.owned_studios.first()
        if owned_studio:
            studio = owned_studio

    if studio is None or studio.owner_doctor_id != doctor_profile.id:
        return render(request, "web_doctor/mobile/my_assistant.html", {"assistants": []})

    assistants = list_platform_assistants_for_doctor(doctor_profile)
    return render(request, "web_doctor/mobile/my_assistant.html", {"assistants": assistants})

