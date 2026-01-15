from django.db import models


class ClinicalEvent(models.Model):
    """临床诊疗事件表。"""

    patient = models.ForeignKey(
        "users.PatientProfile",
        on_delete=models.CASCADE,
        related_name="clinical_events",
        verbose_name="患者",
        help_text="归属患者档案，用于查询与统计。",
    )
    event_date = models.DateField("发生日期", help_text="记录发生/报告日期。")
    event_type = models.PositiveSmallIntegerField(
        "事件类型",
        choices=[
            (1, "门诊"),
            (2, "住院"),
            (3, "复查"),
        ],
        help_text="用于区分门诊/住院/复查。",
    )
    hospital_name = models.CharField(
        "就诊医院",
        max_length=100,
        blank=True,
        help_text="医生端可选填写，用于展示。",
    )
    department_name = models.CharField(
        "就诊科室",
        max_length=50,
        blank=True,
        help_text="医生端可选填写，用于展示。",
    )
    interpretation = models.TextField(
        "报告备注与解读",
        blank=True,
        help_text="用于诊疗记录详情展示的备注/解读内容。",
    )
    files_json = models.JSONField(
        "附件 URL 集合",
        blank=True,
        null=True,
        help_text="诊疗记录关联图片的 URL 列表。",
    )
    created_by_doctor = models.ForeignKey(
        "users.DoctorProfile",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="clinical_events",
        verbose_name="记录医生",
        help_text="记录创建/归档的医生或助理。",
    )
    created_at = models.DateTimeField(
        "记录创建时间",
        auto_now_add=True,
        help_text="用于归档时间展示与排序。",
    )

    class Meta:
        db_table = "health_clinical_events"
        verbose_name = "临床诊疗事件"
        verbose_name_plural = "临床诊疗事件"
        indexes = [
            models.Index(fields=["patient", "event_date"], name="idx_patient_event"),
        ]
