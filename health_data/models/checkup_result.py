"""Structured checkup result storage."""

from __future__ import annotations

from django.db import models

from core.utils.normalization import normalize_standard_field_name


class CheckupResultAbnormalFlag(models.TextChoices):
    LOW = "LOW", "偏低"
    NORMAL = "NORMAL", "正常"
    HIGH = "HIGH", "偏高"
    UNKNOWN = "UNKNOWN", "未知"


class CheckupResultSourceType(models.TextChoices):
    AI = "AI", "AI识别"
    MANUAL = "MANUAL", "人工录入"
    MIGRATED = "MIGRATED", "孤儿重处理"


class OrphanFieldStatus(models.TextChoices):
    PENDING = "PENDING", "待处理"
    RESOLVED = "RESOLVED", "已解决"
    IGNORED = "IGNORED", "已忽略"


class CheckupResultValue(models.Model):
    """Normalized structured values extracted from a report image."""

    patient = models.ForeignKey(
        "users.PatientProfile",
        on_delete=models.CASCADE,
        related_name="checkup_result_values",
        verbose_name="患者",
        help_text="冗余患者，便于按患者和字段聚合查询。",
    )
    report_image = models.ForeignKey(
        "health_data.ReportImage",
        on_delete=models.CASCADE,
        related_name="structured_values",
        verbose_name="来源图片",
        help_text="该结果来自哪一张报告图片。",
    )
    checkup_item = models.ForeignKey(
        "core.CheckupLibrary",
        on_delete=models.PROTECT,
        related_name="structured_result_values",
        verbose_name="检查项",
        help_text="该结果所属检查项，例如血常规、胸部CT。",
    )
    standard_field = models.ForeignKey(
        "core.StandardField",
        on_delete=models.PROTECT,
        related_name="result_values",
        verbose_name="标准字段",
        help_text="最终命中的标准字段。",
    )
    report_date = models.DateField(
        "报告日期",
        help_text="结果对应的报告日期快照。",
    )
    raw_name = models.CharField(
        "原始字段名",
        max_length=100,
        help_text="OCR/AI 识别出的原始名称。",
    )
    normalized_name = models.CharField(
        "归一化字段名",
        max_length=100,
        db_index=True,
        help_text="由原始字段名归一化生成，用于检索与排障。",
    )
    raw_value = models.TextField(
        "原始值文本",
        blank=True,
        help_text="OCR/AI 识别出的原始值文本。",
    )
    value_numeric = models.DecimalField(
        "数值结果",
        max_digits=14,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="数值型标准字段的解析结果。",
    )
    value_text = models.TextField(
        "文本结果",
        blank=True,
        help_text="文本型标准字段的解析结果，如影像描述或医生解读。",
    )
    unit = models.CharField(
        "结果单位",
        max_length=50,
        blank=True,
        help_text="本次报告实际使用的单位快照。",
    )
    lower_bound = models.DecimalField(
        "参考下限",
        max_digits=14,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="报告参考范围下限快照。",
    )
    upper_bound = models.DecimalField(
        "参考上限",
        max_digits=14,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="报告参考范围上限快照。",
    )
    range_text = models.CharField(
        "参考范围原文",
        max_length=100,
        blank=True,
        help_text="原始参考范围文本，例如 3.5-9.5。",
    )
    abnormal_flag = models.CharField(
        "异常标记",
        max_length=16,
        choices=CheckupResultAbnormalFlag.choices,
        default=CheckupResultAbnormalFlag.UNKNOWN,
        help_text="根据数值和上下限得出的结果状态。",
    )
    source_type = models.CharField(
        "来源类型",
        max_length=16,
        choices=CheckupResultSourceType.choices,
        default=CheckupResultSourceType.AI,
        help_text="标记结果来自 AI、人工还是孤儿重处理。",
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "health_checkup_result_values"
        verbose_name = "结构化复查结果"
        verbose_name_plural = "结构化复查结果"
        ordering = ("-report_date", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("report_image", "standard_field"),
                name="uniq_report_image_standard_field",
            )
        ]
        indexes = [
            models.Index(
                fields=["patient", "standard_field", "report_date"],
                name="idx_result_patient_field_date",
            ),
            models.Index(
                fields=["checkup_item", "report_date"],
                name="idx_result_checkup_date",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self.normalized_name:
            self.normalized_name = normalize_standard_field_name(self.raw_name)
        super().save(*args, **kwargs)

    def __str__(self) -> str:  # pragma: no cover - admin display only
        return f"{self.patient_id}-{self.standard_field.local_code}-{self.report_date}"


class CheckupOrphanField(models.Model):
    """Unmatched structured rows awaiting alias or mapping completion."""

    patient = models.ForeignKey(
        "users.PatientProfile",
        on_delete=models.CASCADE,
        related_name="checkup_orphan_fields",
        verbose_name="患者",
        help_text="冗余患者，便于按患者检索孤儿字段。",
    )
    report_image = models.ForeignKey(
        "health_data.ReportImage",
        on_delete=models.CASCADE,
        related_name="orphan_fields",
        verbose_name="来源图片",
        help_text="孤儿字段来自哪一张报告图片。",
    )
    checkup_item = models.ForeignKey(
        "core.CheckupLibrary",
        on_delete=models.PROTECT,
        related_name="orphan_fields",
        verbose_name="检查项",
        help_text="孤儿字段所属检查项。",
    )
    report_date = models.DateField(
        "报告日期",
        help_text="孤儿字段对应的报告日期。",
    )
    raw_name = models.CharField(
        "原始字段名",
        max_length=100,
        help_text="未能正式落库的原始字段名。",
    )
    normalized_name = models.CharField(
        "归一化字段名",
        max_length=100,
        db_index=True,
        help_text="匹配失败后保留的归一化字段名。",
    )
    raw_value = models.TextField(
        "原始值文本",
        blank=True,
        help_text="OCR/AI 识别出的原始值文本。",
    )
    value_numeric = models.DecimalField(
        "数值结果",
        max_digits=14,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="若能解析为数值则保留，供后续转正复用。",
    )
    value_text = models.TextField(
        "文本结果",
        blank=True,
        help_text="若为文本型内容则保留原文本。",
    )
    unit = models.CharField(
        "结果单位",
        max_length=50,
        blank=True,
        help_text="原始识别到的单位。",
    )
    lower_bound = models.DecimalField(
        "参考下限",
        max_digits=14,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="原始识别到的参考范围下限。",
    )
    upper_bound = models.DecimalField(
        "参考上限",
        max_digits=14,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="原始识别到的参考范围上限。",
    )
    range_text = models.CharField(
        "参考范围原文",
        max_length=100,
        blank=True,
        help_text="原始参考范围文本。",
    )
    raw_line_text = models.TextField(
        "原始整行文本",
        blank=True,
        help_text="便于后台回看和排查的整行原文。",
    )
    status = models.CharField(
        "处理状态",
        max_length=16,
        choices=OrphanFieldStatus.choices,
        default=OrphanFieldStatus.PENDING,
        help_text="当前孤儿字段的处理状态。",
    )
    resolved_standard_field = models.ForeignKey(
        "core.StandardField",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="resolved_orphan_fields",
        verbose_name="解决后标准字段",
        help_text="补齐 alias 或映射后最终落到哪个标准字段。",
    )
    resolved_result_value = models.ForeignKey(
        "health_data.CheckupResultValue",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="resolved_orphan_fields",
        verbose_name="解决后正式结果",
        help_text="孤儿字段转正后对应的正式结果记录。",
    )
    resolved_at = models.DateTimeField(
        "解决时间",
        null=True,
        blank=True,
        help_text="孤儿字段被自动或人工解决的时间。",
    )
    notes = models.TextField(
        "处理备注",
        blank=True,
        help_text="后台处理时的附加说明。",
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "health_checkup_orphan_fields"
        verbose_name = "结构化孤儿字段"
        verbose_name_plural = "结构化孤儿字段"
        ordering = ("-report_date", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("report_image", "normalized_name"),
                name="uniq_orphan_report_image_norm_name",
            )
        ]
        indexes = [
            models.Index(
                fields=["normalized_name", "status"],
                name="idx_orphan_norm_status",
            ),
            models.Index(
                fields=["patient", "report_date"],
                name="idx_orphan_patient_date",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self.normalized_name:
            self.normalized_name = normalize_standard_field_name(self.raw_name)
        super().save(*args, **kwargs)

    def __str__(self) -> str:  # pragma: no cover - admin display only
        return f"{self.raw_name} ({self.status})"
