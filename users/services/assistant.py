from django.db.models import QuerySet

from users import choices
from users.models import AssistantProfile, DoctorProfile


def list_platform_assistants_for_doctor(doctor_profile: DoctorProfile) -> QuerySet[AssistantProfile]:
    return (
        AssistantProfile.objects.filter(
            doctors=doctor_profile,
            status=choices.AssistantStatus.ACTIVE,
        )
        .select_related("user")
        .order_by("id")
    )

