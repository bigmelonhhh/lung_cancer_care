from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from business_support.models import FeedbackImage
from users.decorators import check_patient, require_membership
from web_patient.forms import FeedbackForm


@login_required
@check_patient
@require_membership
def feedback_view(request: HttpRequest) -> HttpResponse:
    patient = request.patient
    if request.method == "POST":
        form = FeedbackForm(request.POST)
        if form.is_valid():
            feedback = form.save(commit=False)
            feedback.user = patient
            feedback.save()

            images = request.FILES.getlist("images")
            for image in images[:4]:
                FeedbackImage.objects.create(feedback=feedback, image=image)

            messages.success(request, "感谢反馈，我们会尽快处理！")
            return redirect(reverse("web_patient:patient_dashboard"))
    else:
        form = FeedbackForm()

    return render(
        request,
        "web_patient/feedback.html",
        {
            "form": form,
        },
    )
