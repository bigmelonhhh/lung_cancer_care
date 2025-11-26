from django.db import models


class ClinicalEvent(models.Model):
    """临床诊疗事件表。"""

    patient = models.ForeignKey(
        "users.PatientProfile",
        on_delete=models.CASCADE,
        related_name="clinical_events",
        verbose_name="患者",
    )
    event_date = models.DateField("发生日期")
    event_type = models.PositiveSmallIntegerField(
        "事件类型",
        choices=[
            (1, "门诊"),
            (2, "住院"),
            (3, "复查"),
        ],
    )
    hospital_name = models.CharField("就诊医院", max_length=100, blank=True)
    department_name = models.CharField("就诊科室", max_length=50, blank=True)
    description = models.TextField("诊疗经过", blank=True)
    files_json = models.JSONField("附件 URL 集合", blank=True, null=True)
    created_by_doctor = models.ForeignKey(
        "users.DoctorProfile",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="clinical_events",
        verbose_name="记录医生",
    )
    created_at = models.DateTimeField("记录创建时间", auto_now_add=True)

    class Meta:
        db_table = "health_clinical_events"
        verbose_name = "临床诊疗事件"
        verbose_name_plural = "临床诊疗事件"
        indexes = [
            models.Index(fields=["patient", "event_date"], name="idx_patient_event"),
        ]
