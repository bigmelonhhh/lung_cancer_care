"""Admin for Questionnaire system."""

from django.contrib import admin, messages

from core.models import Questionnaire, QuestionnaireOption, QuestionnaireQuestion


class QuestionnaireOptionInline(admin.TabularInline):
    """题目选项内联编辑（显示在题目详情页）。"""

    model = QuestionnaireOption
    extra = 0
    fields = ("seq", "text", "value", "score")
    ordering = ("seq",)


@admin.register(QuestionnaireQuestion)
class QuestionnaireQuestionAdmin(admin.ModelAdmin):
    """题目管理，支持选项内联。"""

    list_display = ("text_preview", "questionnaire", "section", "q_type", "seq", "is_required")
    list_filter = ("questionnaire", "q_type", "is_required")
    search_fields = ("text", "questionnaire__name")
    ordering = ("questionnaire", "seq")
    inlines = [QuestionnaireOptionInline]
    autocomplete_fields = ["questionnaire"]

    def text_preview(self, obj):
        return obj.text[:50] + "..." if len(obj.text) > 50 else obj.text

    text_preview.short_description = "题目内容"


class QuestionnaireQuestionInline(admin.TabularInline):
    """问卷题目内联编辑（显示在问卷详情页）。"""

    model = QuestionnaireQuestion
    extra = 0
    fields = ("seq", "section", "text", "q_type", "is_required", "weight")
    ordering = ("seq",)
    show_change_link = True  # 关键：允许跳转到题目详情页编辑选项


@admin.register(Questionnaire)
class QuestionnaireAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "metric_type",
        "is_active",
        "sort_order",
    )
    list_editable = ("sort_order",)
    search_fields = ("name", "code")
    list_filter = ("is_active",)
    ordering = ("sort_order", "name")
    actions = ("mark_active", "mark_inactive")
    inlines = [QuestionnaireQuestionInline]

    def get_actions(self, request):
        actions = super().get_actions(request)
        if "delete_selected" in actions:
            del actions["delete_selected"]
        return actions

    @admin.action(description="标记为启用")
    def mark_active(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"已启用 {updated} 个问卷。", messages.SUCCESS)

    @admin.action(description="标记为停用")
    def mark_inactive(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"已停用 {updated} 个问卷。", messages.SUCCESS)

    def delete_model(self, request, obj):
        """重写单条删除为软删除。"""
        self._soft_delete(obj)
        self.message_user(request, f"问卷“{obj}”已标记为停用。", messages.INFO)

    def delete_queryset(self, request, queryset):
        """重写批量删除为软删除。"""
        count = 0
        for obj in queryset:
            if self._soft_delete(obj):
                count += 1
        if count:
            self.message_user(request, f"{count} 个问卷已标记为停用。", messages.INFO)

    def _soft_delete(self, obj: Questionnaire) -> bool:
        if not obj.is_active:
            return False
        obj.is_active = False
        obj.save(update_fields=["is_active"])
        return True