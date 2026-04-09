"""Standard field master data for structured checkup results."""

from __future__ import annotations

from django.db import models

from core.utils.normalization import normalize_standard_field_name


class StandardFieldValueType(models.TextChoices):
    """Supported storage types for standard fields."""

    DECIMAL = "DECIMAL", "数值"
    TEXT = "TEXT", "文本"


class StandardField(models.Model):
    """Standard field definition shared across checkup items."""

    local_code = models.CharField(
        "本地标准编码",
        max_length=64,
        unique=True,
        help_text="系统内部稳定编码，例如 WBC、ALT、IMG_FINDINGS。",
    )
    english_abbr = models.CharField(
        "英文简称",
        max_length=64,
        blank=True,
        help_text="字段简称，例如 WBC、ALT；可为空。",
    )
    chinese_name = models.CharField(
        "中文标准名",
        max_length=100,
        help_text="用于后台展示的规范中文名称。",
    )
    value_type = models.CharField(
        "值类型",
        max_length=16,
        choices=StandardFieldValueType.choices,
        default=StandardFieldValueType.DECIMAL,
        help_text="结果值存储方式，仅支持数值或文本。",
    )
    default_unit = models.CharField(
        "默认单位",
        max_length=50,
        blank=True,
        help_text="默认展示单位，例如 g/L、10^9/L；文本字段可留空。",
    )
    description = models.TextField(
        "字段说明",
        blank=True,
        help_text="补充该字段的业务含义或使用说明。",
    )
    is_active = models.BooleanField("是否启用", default=True)
    sort_order = models.PositiveIntegerField("排序权重", default=0)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "core_standard_fields"
        verbose_name = "标准字段"
        verbose_name_plural = "标准字段"
        ordering = ("sort_order", "local_code")

    def __str__(self) -> str:  # pragma: no cover - admin display only
        return f"{self.chinese_name} ({self.local_code})"


class StandardFieldAlias(models.Model):
    """Alias entries used for OCR/AI field matching."""

    standard_field = models.ForeignKey(
        "core.StandardField",
        on_delete=models.CASCADE,
        related_name="aliases",
        verbose_name="所属标准字段",
        help_text="别名最终指向的标准字段。",
    )
    alias_name = models.CharField(
        "别名原文",
        max_length=100,
        help_text="OCR/AI 可能识别出的原始名称。",
    )
    normalized_name = models.CharField(
        "归一化名称",
        max_length=100,
        unique=True,
        db_index=True,
        editable=False,
        help_text="系统自动生成，用于唯一匹配。",
    )
    is_active = models.BooleanField("是否启用", default=True)
    notes = models.TextField(
        "备注",
        blank=True,
        help_text="记录该别名来源医院或特殊说明。",
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "core_standard_field_aliases"
        verbose_name = "标准字段别名"
        verbose_name_plural = "标准字段别名"
        ordering = ("alias_name", "id")

    def save(self, *args, **kwargs):
        self.normalized_name = normalize_standard_field_name(self.alias_name)
        super().save(*args, **kwargs)

    def __str__(self) -> str:  # pragma: no cover - admin display only
        return f"{self.alias_name} -> {self.standard_field.local_code}"


class CheckupFieldMapping(models.Model):
    """Many-to-many bridge between checkup items and standard fields."""

    checkup_item = models.ForeignKey(
        "core.CheckupLibrary",
        on_delete=models.CASCADE,
        related_name="standard_field_mappings",
        verbose_name="检查项",
        help_text="允许使用该字段的检查项。",
    )
    standard_field = models.ForeignKey(
        "core.StandardField",
        on_delete=models.CASCADE,
        related_name="checkup_mappings",
        verbose_name="标准字段",
        help_text="当前检查项支持的标准字段。",
    )
    sort_order = models.PositiveIntegerField(
        "排序权重",
        default=0,
        help_text="该字段在当前检查项下的展示顺序。",
    )
    is_active = models.BooleanField("是否启用", default=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "core_checkup_field_mappings"
        verbose_name = "检查项字段映射"
        verbose_name_plural = "检查项字段映射"
        ordering = ("sort_order", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("checkup_item", "standard_field"),
                name="uniq_checkup_standard_field",
            )
        ]

    def __str__(self) -> str:  # pragma: no cover - admin display only
        return f"{self.checkup_item} -> {self.standard_field.local_code}"
