"""Admin for structured checkup master data."""

from django.contrib import admin, messages

from core.models import CheckupFieldMapping, StandardField, StandardFieldAlias
from health_data.services.checkup_results import reprocess_orphan_fields


class StandardFieldAliasInline(admin.TabularInline):
    model = StandardFieldAlias
    extra = 0
    fields = ("alias_name", "normalized_name", "is_active", "notes")
    readonly_fields = ("normalized_name",)
    ordering = ("alias_name", "id")


class CheckupFieldMappingInlineForField(admin.TabularInline):
    model = CheckupFieldMapping
    extra = 0
    fields = ("checkup_item", "sort_order", "is_active")
    autocomplete_fields = ("checkup_item",)
    ordering = ("sort_order", "id")


@admin.register(StandardField)
class StandardFieldAdmin(admin.ModelAdmin):
    list_display = (
        "local_code",
        "chinese_name",
        "english_abbr",
        "value_type",
        "default_unit",
        "is_active",
        "sort_order",
    )
    list_editable = ("sort_order",)
    search_fields = ("local_code", "chinese_name", "english_abbr")
    list_filter = ("value_type", "is_active")
    ordering = ("sort_order", "local_code")
    actions = ("mark_active", "mark_inactive")
    inlines = [StandardFieldAliasInline, CheckupFieldMappingInlineForField]

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions

    @admin.action(description="标记为启用")
    def mark_active(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"已启用 {updated} 个标准字段。", messages.SUCCESS)

    @admin.action(description="标记为停用")
    def mark_inactive(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"已停用 {updated} 个标准字段。", messages.SUCCESS)


@admin.register(StandardFieldAlias)
class StandardFieldAliasAdmin(admin.ModelAdmin):
    list_display = ("alias_name", "normalized_name", "standard_field", "is_active")
    search_fields = (
        "alias_name",
        "normalized_name",
        "standard_field__chinese_name",
        "standard_field__local_code",
    )
    list_filter = ("is_active",)
    ordering = ("alias_name", "id")
    autocomplete_fields = ("standard_field",)
    readonly_fields = ("normalized_name",)
    actions = ("mark_active", "mark_inactive", "reprocess_related_orphans")

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions

    @admin.action(description="标记为启用")
    def mark_active(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"已启用 {updated} 个字段别名。", messages.SUCCESS)

    @admin.action(description="标记为停用")
    def mark_inactive(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"已停用 {updated} 个字段别名。", messages.SUCCESS)

    @admin.action(description="重跑受影响孤儿")
    def reprocess_related_orphans(self, request, queryset):
        normalized_names = list(queryset.values_list("normalized_name", flat=True))
        stats = reprocess_orphan_fields(normalized_names=normalized_names)
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
