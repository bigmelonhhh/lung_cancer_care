from django.contrib import admin

from core.models import SystemDocument


@admin.register(SystemDocument)
class SystemDocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "key", "version", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("title", "key")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (
            "基础信息",
            {
                "fields": (
                    "title",
                    "key",
                    "version",
                    "is_active",
                )
            },
        ),
        (
            "正文内容（支持 Markdown）",
            {
                "fields": ("content",),
                "description": "可使用 Markdown 语法（# 一级标题、## 二级标题、- 列表、**加粗** 等），前端会自动渲染为排版良好的页面。",
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

    def get_readonly_fields(self, request, obj=None):
        base = list(super().get_readonly_fields(request, obj))
        if obj:
            base.append("key")
        return tuple(base)

