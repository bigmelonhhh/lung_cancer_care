from django.contrib import admin

from .models import Product, Order


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "price", "duration_days", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name",)
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (
            "基础信息",
            {
                "fields": (
                    "name",
                    "price",
                    "duration_days",
                    "service_content",
                )
            },
        ),
        (
            "状态控制",
            {
                "fields": ("is_active",),
            },
        ),
        (
            "系统信息",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        base = super().get_readonly_fields(request, obj)
        if obj:  # 编辑时只允许修改 is_active
            return base + ("name", "price", "duration_days")
        return base


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("order_no", "patient", "product", "amount", "status", "paid_at")
    list_filter = ("status",)
    search_fields = ("order_no",)
    readonly_fields = ("order_no", "paid_at", "created_at", "updated_at")

    def get_readonly_fields(self, request, obj=None):
        base = list(super().get_readonly_fields(request, obj))
        if obj:
            return tuple(base)
        return tuple(base)

    def save_model(self, request, obj, form, change):
        if not change:
            if not obj.amount:
                obj.amount = obj.product.price
            if obj.status == Order.Status.PAID and not obj.paid_at:
                obj.paid_at = obj.created_at
        super().save_model(request, obj, form, change)

    def has_delete_permission(self, request, obj=None):
        return False
