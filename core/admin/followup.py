"""Admin for follow-up library."""

from django.contrib import admin, messages

from core.models import FollowupLibrary


@admin.register(FollowupLibrary)
class FollowupLibraryAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "schedule_days_template",
        "is_active",
        "sort_order",
    )
    list_editable = ("sort_order",)
    search_fields = ("name", "code")
    list_filter = ("is_active",)
    ordering = ("sort_order", "name")
    actions = ("mark_active", "mark_inactive")

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions

    @admin.action(description="标记为启用")
    def mark_active(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"已启用 {updated} 个随访模板。", messages.SUCCESS)

    @admin.action(description="标记为停用")
    def mark_inactive(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"已停用 {updated} 个随访模板。", messages.SUCCESS)

    def delete_model(self, request, obj):
        self._soft_delete(obj)
        self.message_user(request, f"模板“{obj}”已标记为停用。", messages.INFO)

    def delete_queryset(self, request, queryset):
        count = 0
        for obj in queryset:
            count += int(self._soft_delete(obj))
        if count:
            self.message_user(request, f"{count} 个模板已标记为停用。", messages.INFO)

    def _soft_delete(self, obj: FollowupLibrary) -> bool:
        if not obj.is_active:
            return False
        obj.is_active = False
        obj.save(update_fields=["is_active"])
        return True

