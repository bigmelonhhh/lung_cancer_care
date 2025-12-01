from django.contrib import admin
from django.utils.html import format_html

from core.models import Feedback, FeedbackImage


class FeedbackImageInline(admin.TabularInline):
    model = FeedbackImage
    extra = 0
    readonly_fields = ("thumbnail",)
    fields = ("image", "thumbnail")

    def thumbnail(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="max-height:80px;border-radius:6px;" />',
                obj.image.url,
            )
        return "-"

    thumbnail.short_description = "预览"


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "feedback_type",
        "status",
        "contact_phone",
        "image_preview",
        "created_at",
    )
    list_filter = ("feedback_type", "status", "created_at")
    search_fields = ("content", "contact_phone", "user__name")
    inlines = [FeedbackImageInline]
    readonly_fields = ("created_at",)

    def image_preview(self, obj: Feedback):
        count = obj.images.count()
        if count == 0:
            return "无"
        first = obj.images.first()
        if first and first.image:
            return format_html(
                '<a href="{}" target="_blank">查看图片 ({} 张)</a>',
                first.image.url,
                count,
            )
        return f"{count} 张"

    image_preview.short_description = "图片"
