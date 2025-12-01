import json

from django.contrib import admin, messages
from django.contrib.admin.options import IS_POPUP_VAR
from django.contrib.admin.templatetags.admin_urls import add_preserved_filters
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import reverse

from core.models import Device


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    actions = ("deactivate_unbound",)
    list_display = (
        "sn",
        "imei",
        "model_name",
        "device_type",
        "current_patient",
        "is_active",
        "last_active_at",
    )
    search_fields = (
        "sn",
        "imei",
        "model_name",
        "ble_name",
        "current_patient__name",
    )
    list_filter = ("device_type", "is_active")
    readonly_fields = ("created_at", "updated_at")

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions

    @admin.action(description="停用未绑定的设备")
    def deactivate_unbound(self, request, queryset):
        result = self._soft_delete_queryset(request, queryset)
        if result["deactivated"]:
            self.message_user(
                request,
                f"成功停用 {result['deactivated']} 台未绑定的设备。",
                messages.SUCCESS,
            )
        if result["already_inactive"]:
            self.message_user(
                request,
                f"{result['already_inactive']} 台设备已处于停用状态，无需重复操作。",
                messages.INFO,
            )
        if result["blocked"]:
            self.message_user(
                request,
                f"{result['blocked']} 台设备仍绑定患者，无法停用。",
                messages.ERROR,
            )

    def delete_model(self, request, obj):
        request._device_soft_delete_state = self._soft_delete_object(request, obj)

    def delete_queryset(self, request, queryset):
        self._soft_delete_queryset(request, queryset)

    def log_deletions(self, request, queryset):
        # 覆盖默认的删除日志记录，避免产生“物理删除”日志。
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

        state = getattr(request, "_device_soft_delete_state", "blocked")
        if hasattr(request, "_device_soft_delete_state"):
            delattr(request, "_device_soft_delete_state")

        if state == "success":
            message = f"设备“{obj_display}”已成功停用。"
            level = messages.SUCCESS
        elif state == "already_inactive":
            message = f"设备“{obj_display}”已处于停用状态，无需重复删除。"
            level = messages.INFO
        else:
            message = f"设备“{obj_display}”仍绑定患者，无法删除。"
            level = messages.ERROR
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

    def _soft_delete_object(self, request, obj: Device) -> str:
        if obj.current_patient_id:
            return "blocked"
        if not obj.is_active:
            return "already_inactive"
        obj.is_active = False
        obj.save(update_fields=["is_active"])
        self.log_change(request, obj, "标记为停用（软删除）")
        return "success"

    def _soft_delete_queryset(self, request, queryset):
        unbound = list(queryset.filter(current_patient__isnull=True))
        blocked_count = queryset.exclude(current_patient__isnull=True).count()
        to_deactivate = [obj for obj in unbound if obj.is_active]
        already_inactive = len(unbound) - len(to_deactivate)
        if to_deactivate:
            ids = [obj.pk for obj in to_deactivate]
            self.model.objects.filter(pk__in=ids).update(is_active=False)
            for obj in to_deactivate:
                obj.is_active = False
                self.log_change(request, obj, "标记为停用（软删除）")
        return {
            "deactivated": len(to_deactivate),
            "already_inactive": already_inactive,
            "blocked": blocked_count,
        }
