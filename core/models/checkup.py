"""复查项目标准库。"""

from django.db import models

from . import choices


class CheckupLibrary(models.Model):
    """复查检查项目主数据，配好后供计划引用。"""

    name = models.CharField("项目名称", max_length=50)
    code = models.CharField(
        "项目编码",
        max_length=50,
        unique=True,
        help_text="英文编码，例如 BLOOD_ROUTINE/CT_CHEST。",
    )
    schedule_days_template = models.JSONField(
        "推荐执行天(周期内)",
        default=list,
        blank=True,
        help_text="周期天数列表，例如 [3, 8] 或 [1,2,...,21]。",
    )
    category = models.PositiveSmallIntegerField(
        "分类",
        choices=choices.CheckupCategory.choices,
        default=choices.CheckupCategory.IMAGING,
    )
    related_report_type = models.PositiveSmallIntegerField(
        "关联报告类型",
        choices=choices.ReportType.choices,
        null=True,
        blank=True,
        help_text="上传该报告类型时自动核销任务。",
    )
    is_active = models.BooleanField("是否启用", default=True)
    sort_order = models.PositiveIntegerField("排序权重", default=0)

    class Meta:
        db_table = "core_checkup_library"
        verbose_name = "复查项目"
        verbose_name_plural = "复查项目"
        ordering = ("sort_order", "name")

    def __str__(self) -> str:  # pragma: no cover - 用于后台展示
        return self.name
