from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from users.decorators import check_assistant


@login_required
@check_assistant
def mobile_related_doctors(request: HttpRequest) -> HttpResponse:
    assistant_profile = getattr(request.user, "assistant_profile", None)
    if assistant_profile is None:
        return render(
            request,
            "web_doctor/mobile/related_doctors.html",
            {"related_doctors": []},
        )

    related_doctors = (
        assistant_profile.doctors.filter(owned_studios__isnull=False)
        .select_related("user")
        .order_by("id")
        .distinct()
    )
    return render(
        request,
        "web_doctor/mobile/related_doctors.html",
        {"related_doctors": related_doctors},
    )
