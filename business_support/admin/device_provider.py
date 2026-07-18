from django.contrib import admin

from business_support.models import DeviceProvider


@admin.register(DeviceProvider)
class DeviceProviderAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active", "device_count", "updated_at")
    search_fields = ("code", "name", "description")
    list_filter = ("is_active",)
    readonly_fields = ("created_at", "updated_at")
    ordering = ("code",)

    @admin.display(description="设备数量")
    def device_count(self, obj: DeviceProvider) -> int:
        return obj.devices.count()
