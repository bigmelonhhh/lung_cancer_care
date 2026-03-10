from django.db import models
from django.utils import timezone


class AlertEventType(models.TextChoices):
    DATA = "data", "Data Anomaly"
    BEHAVIOR = "behavior", "Behavior Anomaly"
    ARCHIVE = "archive", "New Record"
    QUESTIONNAIRE = "questionnaire", "Questionnaire Anomaly"
    OTHER = "other", "Other"


class AlertLevel(models.IntegerChoices):
    MILD = 1, "Mild"
    MODERATE = 2, "Moderate"
    SEVERE = 3, "Severe"


class AlertStatus(models.IntegerChoices):
    PENDING = 1, "Pending"
    ESCALATED = 2, "Escalated"
    COMPLETED = 3, "Completed"


class PatientAlert(models.Model):
    patient = models.ForeignKey(
        "users.PatientProfile",
        on_delete=models.CASCADE,
        related_name="patient_alerts",
        verbose_name="Patient",
        help_text="Target patient profile for this alert.",
    )
    doctor = models.ForeignKey(
        "users.DoctorProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="patient_alerts",
        verbose_name="Assigned doctor",
        help_text="Doctor responsible for follow-up.",
    )
    event_type = models.CharField(
        "Event type",
        max_length=30,
        choices=AlertEventType.choices,
        help_text="Category of the alert.",
    )
    event_level = models.PositiveSmallIntegerField(
        "Event level",
        choices=AlertLevel.choices,
        help_text="Severity level of the alert.",
    )
    event_title = models.CharField(
        "Event title",
        max_length=200,
        help_text="Short title shown in the todo list.",
    )
    event_content = models.TextField(
        "Event content",
        blank=True,
        help_text="Detailed description for follow-up.",
    )
    event_time = models.DateTimeField(
        "Event time",
        default=timezone.now,
        help_text="When the alert was triggered.",
    )
    status = models.PositiveSmallIntegerField(
        "Status",
        choices=AlertStatus.choices,
        default=AlertStatus.PENDING,
        help_text="Follow-up status for this alert.",
    )
    handler = models.ForeignKey(
        "users.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="handled_patient_alerts",
        verbose_name="Handler",
        help_text="User who handled the alert.",
    )
    handle_time = models.DateTimeField(
        "Handled time",
        null=True,
        blank=True,
        help_text="When the alert was handled.",
    )
    handle_content = models.TextField(
        "Handle content",
        blank=True,
        help_text="Handling notes or resolution details.",
    )
    handle_meta = models.JSONField(
        "Handle meta",
        default=dict,
        blank=True,
        help_text="Latest handling snapshot and full handling history.",
    )
    source_type = models.CharField(
        "Source type",
        max_length=50,
        blank=True,
        help_text="Origin type, e.g. metric or questionnaire.",
    )
    source_id = models.BigIntegerField(
        "Source ID",
        null=True,
        blank=True,
        help_text="Origin record ID.",
    )
    source_payload = models.JSONField(
        "Source payload",
        default=dict,
        blank=True,
        help_text="Snapshot of source details.",
    )
    is_active = models.BooleanField(
        "Is active",
        default=True,
        help_text="Soft disable flag.",
    )
    created_at = models.DateTimeField(
        "Created at",
        auto_now_add=True,
        help_text="Record creation time.",
    )
    updated_at = models.DateTimeField(
        "Updated at",
        auto_now=True,
        help_text="Record update time.",
    )

    class Meta:
        db_table = "patient_alerts"
        verbose_name = "Patient alert"
        verbose_name_plural = "Patient alerts"
        ordering = ("-event_time", "-id")
        indexes = [
            models.Index(fields=["patient", "status"]),
            models.Index(fields=["doctor", "status"]),
            models.Index(fields=["event_type", "event_level"]),
            models.Index(fields=["event_time"]),
        ]

    def __str__(self) -> str:
        return f"{self.patient_id} - {self.event_title}"
