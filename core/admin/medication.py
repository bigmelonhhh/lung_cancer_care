import json

from django.contrib import admin, messages
from django.contrib.admin.options import IS_POPUP_VAR
from django.contrib.admin.templatetags.admin_urls import add_preserved_filters
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import reverse

from core.models import Medication


@admin.register(Medication)
class MedicationAdmin(admin.ModelAdmin):
    actions = ("mark_inactive",)
    list_display = (
        "name",
        "trade_names",
        "abbr_display",
        "drug_type",
        "target_gene",
        "is_active",
    )
    search_fields = (
        "name",
        "trade_names",
        "name_abbr",
        "trade_names_abbr",
    )
    list_filter = ("drug_type", "method", "is_active")

    fieldsets = (
        (
            "基础信息",
            {
                "fields": (
                    "name",
                    "trade_names",
                    "drug_type",
                    "method",
                )
            },
        ),
        (
            "拼音简码（系统自动生成，仅展示）",
            {
                "fields": (
                    "name_abbr",
                    "trade_names_abbr",
                )
            },
        ),
        (
            "推荐用法",
            {
                "fields": (
                    "target_gene",
                    "default_dosage",
                    "default_frequency",
                    "schedule_days_template",
                )
            },
        ),
        (
            "其它",
            {
                "fields": (
                    "description",
                    "is_active",
                )
            },
        ),
    )

    def abbr_display(self, obj: Medication) -> str:
        parts = [obj.name_abbr or "", obj.trade_names_abbr or ""]
        # 显示为 "AXTN / TRS" 或单个简码
        return " / ".join([p for p in parts if p])

    abbr_display.short_description = "简码"

    readonly_fields = ("name_abbr", "trade_names_abbr")

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions

    @admin.action(description="标记所选药物为未启用")
    def mark_inactive(self, request, queryset):
        updated = self._soft_delete_queryset(request, queryset)
        if updated:
            self.message_user(
                request,
                f"成功标记 {updated} 个药物为未启用。",
                messages.SUCCESS,
            )
        else:
            self.message_user(
                request,
                "所选药物均已是未启用状态。",
                messages.INFO,
            )

    def delete_model(self, request, obj):
        request._medication_soft_delete_result = self._soft_delete_object(request, obj)

    def delete_queryset(self, request, queryset):
        self._soft_delete_queryset(request, queryset)

    def log_deletions(self, request, queryset):
        # 覆盖默认的删除日志记录，避免把软删除写入删除日志。
        return

    def response_delete(self, request, obj_display, obj_id):
        if IS_POPUP_VAR in request.POST:
            popup_response_data = json.dumps(
                {
                    "action": "delete",
                    "value": str(obj_id),
                }
            )
            return TemplateResponse(
                request,
                self.popup_response_template
                or [
                    "admin/%s/%s/popup_response.html"
                    % (self.opts.app_label, self.opts.model_name),
                    "admin/%s/popup_response.html" % self.opts.app_label,
                    "admin/popup_response.html",
                ],
                {
                    "popup_response_data": popup_response_data,
                },
            )

        deactivated = getattr(request, "_medication_soft_delete_result", False)
        if hasattr(request, "_medication_soft_delete_result"):
            delattr(request, "_medication_soft_delete_result")
        if deactivated:
            message = f"药物“{obj_display}”已标记为未启用。"
            level = messages.SUCCESS
        else:
            message = f"药物“{obj_display}”已是未启用状态，无需再次停用。"
            level = messages.INFO
        self.message_user(request, message, level)

        if self.has_change_permission(request, None):
            post_url = reverse(
                "admin:%s_%s_changelist" % (self.opts.app_label, self.opts.model_name),
                current_app=self.admin_site.name,
            )
            preserved_filters = self.get_preserved_filters(request)
            post_url = add_preserved_filters(
                {"preserved_filters": preserved_filters, "opts": self.opts}, post_url
            )
        else:
            post_url = reverse("admin:index", current_app=self.admin_site.name)
        return HttpResponseRedirect(post_url)

    def _soft_delete_object(self, request, obj: Medication) -> bool:
        if not obj.is_active:
            return False
        obj.is_active = False
        obj.save(update_fields=["is_active"])
        self.log_change(request, obj, "标记为未启用（软删除）")
        return True

    def _soft_delete_queryset(self, request, queryset):
        objs = list(queryset.filter(is_active=True))
        if not objs:
            return 0
        ids = [obj.pk for obj in objs]
        self.model.objects.filter(pk__in=ids).update(is_active=False)
        for obj in objs:
            obj.is_active = False
            self.log_change(request, obj, "标记为未启用（软删除）")
        return len(ids)
