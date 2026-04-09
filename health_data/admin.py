"""Admin for structured checkup result data."""

from django.contrib import admin, messages

from health_data.models import CheckupOrphanField, CheckupResultValue, OrphanFieldStatus, ReportImage
from health_data.services.checkup_results import reprocess_orphan_fields


@admin.register(CheckupResultValue)
class CheckupResultValueAdmin(admin.ModelAdmin):
    list_display = (
        "patient",
        "checkup_item",
        "standard_field",
        "report_date",
        "abnormal_flag",
        "source_type",
    )
    search_fields = (
        "patient__name",
        "standard_field__chinese_name",
        "standard_field__local_code",
        "raw_name",
    )
    list_filter = ("source_type", "abnormal_flag", "checkup_item")
    ordering = ("-report_date", "-id")
    readonly_fields = (
        "patient",
        "report_image",
        "checkup_item",
        "standard_field",
        "report_date",
        "raw_name",
        "normalized_name",
        "raw_value",
        "value_numeric",
        "value_text",
        "unit",
        "lower_bound",
        "upper_bound",
        "range_text",
        "abnormal_flag",
        "source_type",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False


@admin.register(CheckupOrphanField)
class CheckupOrphanFieldAdmin(admin.ModelAdmin):
    list_display = (
        "raw_name",
        "normalized_name",
        "checkup_item",
        "report_image",
        "report_date",
        "status",
    )
    search_fields = ("raw_name", "normalized_name")
    list_filter = ("status", "checkup_item")
    ordering = ("-report_date", "-id")
    readonly_fields = (
        "patient",
        "report_image",
        "checkup_item",
        "report_date",
        "raw_name",
        "normalized_name",
        "raw_value",
        "value_numeric",
        "value_text",
        "unit",
        "lower_bound",
        "upper_bound",
        "range_text",
        "raw_line_text",
        "resolved_standard_field",
        "resolved_result_value",
        "resolved_at",
        "created_at",
        "updated_at",
    )
    actions = ("retry_matching", "mark_ignored")

    @admin.action(description="重试匹配选中孤儿")
    def retry_matching(self, request, queryset):
        stats = reprocess_orphan_fields(queryset=queryset)
        self.message_user(
            request,
            (
                "孤儿重跑完成："
                f"已解决 {stats['resolved']} 条，"
                f"缺少别名 {stats['missing_alias']} 条，"
                f"缺少映射 {stats['missing_mapping']} 条。"
            ),
            messages.SUCCESS,
        )

    @admin.action(description="标记为忽略")
    def mark_ignored(self, request, queryset):
        updated = queryset.filter(status=OrphanFieldStatus.PENDING).update(
            status=OrphanFieldStatus.IGNORED
        )
        self.message_user(request, f"已忽略 {updated} 条孤儿字段。", messages.SUCCESS)

    def has_add_permission(self, request):
        return False


@admin.register(ReportImage)
class ReportImageAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "upload",
        "record_type",
        "checkup_item",
        "report_date",
        "ai_parse_status",
        "ai_parsed_at",
    )
    search_fields = ("image_url", "ocr_text", "checkup_item__name", "upload__patient__name")
    list_filter = ("record_type", "ai_parse_status", "checkup_item")
    ordering = ("-id",)
    readonly_fields = (
        "upload",
        "image_url",
        "record_type",
        "checkup_item",
        "report_date",
        "health_metric",
        "clinical_event",
        "archived_by",
        "archived_at",
        "ocr_text",
        "ai_parse_status",
        "ai_structured_json",
        "ai_model_name",
        "ai_parsed_at",
        "ai_error_message",
    )
