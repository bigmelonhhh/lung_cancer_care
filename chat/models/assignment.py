from django.db import models
from django.utils import timezone

from users.models.base import TimeStampedModel


class PatientStudioAssignment(TimeStampedModel):
    """
    [Purpose]
    - Track patient-to-studio assignment history.
    """

    patient = models.ForeignKey(
        "users.PatientProfile",
        on_delete=models.CASCADE,
        related_name="studio_assignments",
        verbose_name="Patient",
        help_text="Patient profile assigned to a studio.",
    )
    studio = models.ForeignKey(
        "users.DoctorStudio",
        on_delete=models.CASCADE,
        related_name="patient_assignments",
        verbose_name="Studio",
        help_text="Studio assigned to the patient.",
    )
    start_at = models.DateTimeField(
        "Start At",
        default=timezone.now,
        help_text="Assignment start timestamp.",
    )
    end_at = models.DateTimeField(
        "End At",
        null=True,
        blank=True,
        help_text="Assignment end timestamp, null means active.",
    )
    reason = models.TextField(
        "Reason",
        blank=True,
        help_text="Optional transfer reason note.",
    )

    class Meta:
        verbose_name = "Patient Studio Assignment"
        verbose_name_plural = "Patient Studio Assignments"
        indexes = [
            models.Index(fields=["patient", "end_at"], name="idx_chat_assignment_active"),
        ]

    def __str__(self) -> str:
        return f"Assignment#Patient{self.patient_id}-Studio{self.studio_id}"
