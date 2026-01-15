from django.db import models


class UploadSource(models.IntegerChoices):
    """上传入口枚举。"""

    PERSONAL_CENTER = 1, "个人中心"
    CHECKUP_PLAN = 2, "复查计划"
    DOCTOR_BACKEND = 3, "医生后台"


class UploaderRole(models.IntegerChoices):
    """上传人角色枚举（用于展示/统计）。"""

    PATIENT = 1, "患者/家属"
    DOCTOR = 2, "医生"
    ASSISTANT = 3, "医生助理"
    ADMIN = 4, "平台管理员"


class ReportUpload(models.Model):
    """报告上传批次：一次上传动作，对应多张图片，供图片档案分组展示。"""

    patient = models.ForeignKey(
        "users.PatientProfile",
        on_delete=models.CASCADE,
        related_name="report_uploads",
        verbose_name="患者",
        help_text="用于归属患者档案与查询。",
    )
    upload_source = models.PositiveSmallIntegerField(
        "上传入口",
        choices=UploadSource.choices,
        default=UploadSource.PERSONAL_CENTER,
        help_text="用于区分个人中心/复查计划/医生端上传场景。",
    )
    uploader = models.ForeignKey(
        "users.CustomUser",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="report_uploads",
        verbose_name="上传人账号",
        help_text="指向系统账号，用于展示上传人身份。",
    )
    uploader_role = models.PositiveSmallIntegerField(
        "上传人角色",
        choices=UploaderRole.choices,
        default=UploaderRole.PATIENT,
        help_text="用于上传人标签展示与统计口径。",
    )
    related_task = models.ForeignKey(
        "core.DailyTask",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="report_uploads",
        verbose_name="关联复查任务",
        help_text="复查计划入口上传时，绑定对应任务用于核销。",
    )
    created_at = models.DateTimeField(
        "上传时间",
        auto_now_add=True,
        help_text="用于个人中心按上传日期分组展示。",
    )
    deleted_at = models.DateTimeField(
        "删除时间",
        null=True,
        blank=True,
        help_text="患者删除上传记录时标记；已归档图片不删除。",
    )

    class Meta:
        db_table = "health_report_uploads"
        verbose_name = "报告上传批次"
        verbose_name_plural = "报告上传批次"
        indexes = [
            models.Index(fields=["patient", "created_at"], name="idx_report_upload_patient_date"),
        ]

    def __str__(self) -> str:  # pragma: no cover - 后台展示
        return f"{self.patient_id} - {self.created_at}"


class ReportImage(models.Model):
    """报告图片明细：单张图片的类目与归档状态。"""

    class RecordType(models.IntegerChoices):
        """诊疗记录一级类目。"""

        OUTPATIENT = 1, "门诊"
        INPATIENT = 2, "住院"
        CHECKUP = 3, "复查"

    upload = models.ForeignKey(
        "health_data.ReportUpload",
        on_delete=models.CASCADE,
        related_name="images",
        verbose_name="上传批次",
        help_text="用于把多张图片归为同一次上传。",
    )
    image_url = models.URLField(
        "图片地址",
        max_length=500,
        help_text="存储上传后的可访问地址。",
    )
    record_type = models.PositiveSmallIntegerField(
        "记录类型",
        choices=RecordType.choices,
        null=True,
        blank=True,
        help_text="诊疗记录一级类目；未归档时可为空。",
    )
    checkup_item = models.ForeignKey(
        "core.CheckupLibrary",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="report_images",
        verbose_name="复查项目",
        help_text="复查二级类目，record_type=复查时必填。",
    )
    report_date = models.DateField(
        "报告日期",
        null=True,
        blank=True,
        help_text="报告出具日期，归档时填写。",
    )
    clinical_event = models.ForeignKey(
        "health_data.ClinicalEvent",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="report_images",
        verbose_name="诊疗记录",
        help_text="归档后关联到诊疗记录。",
    )
    archived_by = models.ForeignKey(
        "users.DoctorProfile",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="archived_report_images",
        verbose_name="归档人",
        help_text="记录实际归档操作人。",
    )
    archived_at = models.DateTimeField(
        "归档时间",
        null=True,
        blank=True,
        help_text="医生归档图片的时间。",
    )
    ocr_text = models.TextField(
        "OCR文本",
        blank=True,
        help_text="用于结构化识别/搜索的文本内容。",
    )

    class Meta:
        db_table = "health_report_images"
        verbose_name = "报告图片"
        verbose_name_plural = "报告图片"
        indexes = [
            models.Index(fields=["upload", "record_type"], name="idx_report_image_upload_type"),
            models.Index(fields=["report_date"], name="idx_report_image_date"),
        ]

    def __str__(self) -> str:  # pragma: no cover - 后台展示
        return f"{self.upload_id} - {self.image_url}"
