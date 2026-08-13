from dataclasses import dataclass
from datetime import date
from typing import Literal

from django.utils import timezone

from core.models import TreatmentCycle
from core.models import choices as core_choices


@dataclass(frozen=True)
class HomePlanAccess:
    """Patient-home access capabilities for the daily-plan section."""

    mode: Literal["member", "trial", "locked"]
    can_view_daily_plan: bool
    can_view_steps: bool
    can_view_history: bool


def resolve_home_plan_access(
    patient,
    as_of_date: date | None = None,
) -> HomePlanAccess:
    """Resolve member, trial, or locked access for the patient-home plan."""

    is_member = bool(
        getattr(patient, "is_member", False)
        and getattr(patient, "membership_expire_date", None)
    )
    if is_member:
        return HomePlanAccess(
            mode="member",
            can_view_daily_plan=True,
            can_view_steps=True,
            can_view_history=True,
        )

    target_date = as_of_date or timezone.localdate()
    has_active_cycle = TreatmentCycle.objects.filter(
        patient=patient,
        status=core_choices.TreatmentCycleStatus.IN_PROGRESS,
        start_date__lte=target_date,
        end_date__gte=target_date,
    ).exists()
    if has_active_cycle:
        return HomePlanAccess(
            mode="trial",
            can_view_daily_plan=True,
            can_view_steps=False,
            can_view_history=False,
        )

    return HomePlanAccess(
        mode="locked",
        can_view_daily_plan=False,
        can_view_steps=False,
        can_view_history=False,
    )
