from django.contrib import admin

from business_support.models import SMSLog


@admin.register(SMSLog)
class SMSLogAdmin(admin.ModelAdmin):
    """Expose SMS sending records as a read-only admin audit list."""

    list_display = (
        "created_at",
        "requested_by",
        "phone",
        "content",
        "is_success",
    )
    list_filter = ("is_success", "created_at")
    search_fields = (
        "phone",
        "content",
        "requested_by__username",
        "requested_by__wx_nickname",
    )
    readonly_fields = (
        "requested_by",
        "phone",
        "content",
        "is_success",
        "created_at",
        "updated_at",
    )
    list_select_related = ("requested_by",)
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
