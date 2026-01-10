from django.db import models
from django.utils import timezone

from users.models.base import TimeStampedModel


class PatientStudioAssignment(TimeStampedModel):
    """
    患者工作室归属记录。

    - 记录患者与工作室的归属历史。
    """

    patient = models.ForeignKey(
        "users.PatientProfile",
        on_delete=models.CASCADE,
        related_name="studio_assignments",
        verbose_name="患者",
        help_text="归属到工作室的患者档案。",
    )
    studio = models.ForeignKey(
        "users.DoctorStudio",
        on_delete=models.CASCADE,
        related_name="patient_assignments",
        verbose_name="工作室",
        help_text="患者当前归属的工作室。",
    )
    start_at = models.DateTimeField(
        "开始时间",
        default=timezone.now,
        help_text="归属开始时间。",
    )
    end_at = models.DateTimeField(
        "结束时间",
        null=True,
        blank=True,
        help_text="归属结束时间，空值表示当前仍有效。",
    )
    reason = models.TextField(
        "转移原因",
        blank=True,
        help_text="可选的转移原因说明。",
    )

    class Meta:
        verbose_name = "患者工作室归属"
        verbose_name_plural = "患者工作室归属"
        indexes = [
            models.Index(fields=["patient", "end_at"], name="idx_chat_assignment_active"),
        ]

    def __str__(self) -> str:
        return f"Assignment#Patient{self.patient_id}-Studio{self.studio_id}"
