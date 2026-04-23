"""Admin for structured checkup result data."""

from __future__ import annotations

import json

from django import forms
from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from ai_vision.schemas.report_image import build_empty_report_image_json, sanitize_report_image_json
from core.models import CheckupLibrary
from health_data.models import CheckupOrphanField, CheckupResultValue, OrphanFieldStatus, ReportImage
from health_data.services import (
    analyze_report_image_structured_items,
    rebuild_report_image_structured_results,
)

ABNORMAL_FLAG_CHOICES = (
    ("", "未标注"),
    ("high", "偏高"),
    ("normal", "正常"),
    ("low", "偏低"),
    ("unknown", "未知"),
)

REVIEW_TOP_LEVEL_FIELDS = (
    "is_medical_report",
    "report_category",
    "hospital_name",
    "patient_name",
    "patient_gender",
    "patient_age",
    "sample_type",
    "report_name",
    "report_time_raw",
    "exam_time_raw",
    "exam_findings",
    "doctor_interpretation",
)


def _pretty_json(value) -> str:
    if value in (None, "", [], {}):
        return "-"
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _allowed_report_categories() -> list[str]:
    return list(
        CheckupLibrary.objects.filter(is_active=True).order_by("sort_order", "id").values_list("name", flat=True)
    )


class ReportImageReviewForm(forms.ModelForm):
    is_medical_report = forms.BooleanField(label="是否医疗报告", required=False)
    report_category = forms.ChoiceField(label="报告分类", required=False)
    hospital_name = forms.CharField(label="医院名称", required=False)
    patient_name = forms.CharField(label="患者姓名", required=False)
    patient_gender = forms.CharField(label="患者性别", required=False)
    patient_age = forms.CharField(label="患者年龄", required=False)
    sample_type = forms.CharField(label="样本类型", required=False)
    report_name = forms.CharField(label="报告名称", required=False)
    report_time_raw = forms.CharField(label="报告时间原文", required=False)
    exam_time_raw = forms.CharField(label="检查时间原文", required=False)
    exam_findings = forms.CharField(
        label="检查所见",
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    doctor_interpretation = forms.CharField(
        label="医生解读",
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    reviewed_items_json = forms.CharField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = ReportImage
        fields = ()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["report_category"].choices = [("", "---------")] + [
            (name, name) for name in _allowed_report_categories()
        ]
        if self.is_bound:
            return

        payload = self.instance.get_effective_structured_json() or build_empty_report_image_json()
        for field_name in REVIEW_TOP_LEVEL_FIELDS:
            self.fields[field_name].initial = payload.get(field_name)
        self.fields["reviewed_items_json"].initial = json.dumps(
            payload.get("items") or [],
            ensure_ascii=False,
        )

    def clean_reviewed_items_json(self) -> str:
        raw_value = self.cleaned_data.get("reviewed_items_json") or "[]"
        try:
            data = json.loads(raw_value)
        except json.JSONDecodeError as exc:
            raise forms.ValidationError("项目明细格式不正确。") from exc
        if not isinstance(data, list):
            raise forms.ValidationError("项目明细必须是数组。")

        normalized_rows = []
        for item in data:
            if not isinstance(item, dict):
                raise forms.ValidationError("项目明细中存在非法行。")
            normalized_rows.append(
                {
                    "item_name": item.get("item_name"),
                    "item_value": item.get("item_value"),
                    "abnormal_flag": item.get("abnormal_flag"),
                    "reference_low": item.get("reference_low"),
                    "reference_high": item.get("reference_high"),
                    "unit": item.get("unit"),
                    "item_code": item.get("item_code"),
                }
            )
        return json.dumps(normalized_rows, ensure_ascii=False)

    def clean(self):
        cleaned_data = super().clean()
        try:
            parsed_items = json.loads(cleaned_data.get("reviewed_items_json") or "[]")
        except json.JSONDecodeError:
            parsed_items = []

        payload = {field_name: cleaned_data.get(field_name) for field_name in REVIEW_TOP_LEVEL_FIELDS}
        payload["items"] = parsed_items
        cleaned_data["reviewed_structured_payload"] = sanitize_report_image_json(
            payload,
            allowed_categories=set(_allowed_report_categories()),
        )
        return cleaned_data


@admin.register(CheckupResultValue)
class CheckupResultValueAdmin(admin.ModelAdmin):
    list_display = (
        "patient",
        "checkup_item",
        "standard_field",
        "report_date",
        "abnormal_flag",
        "source_type",
    )
    search_fields = (
        "patient__name",
        "standard_field__chinese_name",
        "standard_field__local_code",
        "raw_name",
    )
    list_filter = ("source_type", "abnormal_flag", "checkup_item")
    ordering = ("-report_date", "-id")
    readonly_fields = (
        "patient",
        "report_image",
        "checkup_item",
        "standard_field",
        "report_date",
        "raw_name",
        "normalized_name",
        "raw_value",
        "item_code",
        "value_numeric",
        "value_text",
        "unit",
        "lower_bound",
        "upper_bound",
        "range_text",
        "abnormal_flag",
        "source_type",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False


@admin.register(CheckupOrphanField)
class CheckupOrphanFieldAdmin(admin.ModelAdmin):
    list_display = (
        "source_image_preview",
        "raw_name",
        "normalized_name",
        "checkup_item",
        "report_image_link",
        "report_date",
        "status",
    )
    search_fields = ("raw_name", "normalized_name")
    list_filter = ("status", "checkup_item")
    list_select_related = ("report_image", "checkup_item")
    ordering = ("-report_date", "-id")
    readonly_fields = (
        "patient",
        "report_image",
        "checkup_item",
        "report_date",
        "raw_name",
        "normalized_name",
        "raw_value",
        "item_code",
        "value_numeric",
        "value_text",
        "unit",
        "lower_bound",
        "upper_bound",
        "range_text",
        "raw_line_text",
        "resolved_standard_field",
        "resolved_result_value",
        "resolved_at",
        "created_at",
        "updated_at",
    )
    actions = ("retry_matching", "mark_ignored")

    @admin.display(description="来源图片")
    def source_image_preview(self, obj):
        if not obj.report_image_id or not obj.report_image.image_url:
            return "-"
        url = reverse("admin:health_data_reportimage_change", args=[obj.report_image_id])
        return format_html(
            '<a href="{}"><img src="{}" alt="来源图片" style="max-width:72px; max-height:72px; border-radius:4px;" /></a>',
            url,
            obj.report_image.image_url,
        )

    @admin.display(description="报告图片")
    def report_image_link(self, obj):
        if not obj.report_image_id:
            return "-"
        url = reverse("admin:health_data_reportimage_change", args=[obj.report_image_id])
        return format_html('<a href="{}">报告图片 #{}</a>', url, obj.report_image_id)

    @admin.action(description="重试匹配")
    def retry_matching(self, request, queryset):
        from health_data.tasks import reprocess_orphan_fields_task

        orphan_ids = list(queryset.values_list("id", flat=True))
        if orphan_ids:
            reprocess_orphan_fields_task.delay(orphan_ids=orphan_ids)
        self.message_user(request, f"已提交 {len(orphan_ids)} 条孤儿字段的异步重跑任务。", messages.SUCCESS)
        return HttpResponseRedirect(request.get_full_path())

    @admin.action(description="标记为忽略")
    def mark_ignored(self, request, queryset):
        updated = queryset.filter(status=OrphanFieldStatus.PENDING).update(
            status=OrphanFieldStatus.IGNORED
        )
        self.message_user(request, f"已忽略 {updated} 条孤儿字段。", messages.SUCCESS)

    def has_add_permission(self, request):
        return False


@admin.register(ReportImage)
class ReportImageAdmin(admin.ModelAdmin):
    form = ReportImageReviewForm
    change_form_template = "admin/health_data/reportimage/change_form.html"
    actions = ("enqueue_ai_extraction",)
    list_display = (
        "id",
        "upload",
        "record_type",
        "checkup_item",
        "report_date",
        "ai_parse_status",
        "ai_parsed_at",
    )
    search_fields = ("image_url", "ocr_text", "checkup_item__name", "upload__patient__name")
    list_filter = ("record_type", "ai_parse_status", "checkup_item")
    list_select_related = ("upload", "checkup_item", "reviewed_by")
    ordering = ("-id",)
    fieldsets = (
        (
            "图片信息",
            {
                "classes": ("report-review-fieldset", "report-review-left-fieldset", "field-image-info"),
                "fields": (
                    ("upload", "record_type", "checkup_item", "report_date"),
                    ("health_metric", "clinical_event"),
                    ("archived_by", "archived_at"),
                    "image_url",
                    "ocr_text_display",
                )
            },
        ),
        (
            "AI结果",
            {
                "classes": ("report-review-fieldset", "report-review-left-fieldset", "field-ai-results"),
                "fields": (
                    ("ai_parse_status", "ai_model_name", "ai_parsed_at"),
                    "raw_ai_json_display",
                    "ai_error_message",
                    "ai_sync_warnings_display",
                )
            },
        ),
        (
            "人工修订",
            {
                "classes": ("report-review-fieldset", "report-review-right-fieldset", "field-review-form"),
                "fields": (
                    ("effective_structured_source", "reviewed_by", "reviewed_at"),
                    ("is_medical_report", "report_category"),
                    ("hospital_name", "patient_name"),
                    ("patient_gender", "patient_age"),
                    ("sample_type", "report_name"),
                    ("report_time_raw", "exam_time_raw"),
                    "exam_findings",
                    "doctor_interpretation",
                )
            },
        ),
    )
    readonly_fields = (
        "upload",
        "record_type",
        "checkup_item",
        "report_date",
        "health_metric",
        "clinical_event",
        "archived_by",
        "archived_at",
        "image_preview",
        "image_url",
        "ocr_text_display",
        "ai_parse_status",
        "ai_model_name",
        "ai_parsed_at",
        "raw_ai_json_display",
        "ai_error_message",
        "ai_sync_warnings_display",
        "effective_structured_source",
        "reviewed_by",
        "reviewed_at",
    )

    @admin.display(description="原图预览")
    def image_preview(self, obj):
        if not obj.image_url:
            return "-"
        return format_html(
            '<img src="{0}" alt="报告图片" style="max-width:100%; max-height:480px; border-radius:6px;" />',
            obj.image_url,
        )

    @admin.display(description="OCR文本")
    def ocr_text_display(self, obj):
        if not obj.ocr_text:
            return "-"
        return format_html(
            "<details><summary>查看 OCR 文本</summary>"
            '<pre style="white-space: pre-wrap; word-break: break-word; margin-top: 8px;">{}</pre>'
            "</details>",
            obj.ocr_text,
        )

    @admin.display(description="原始 AI JSON")
    def raw_ai_json_display(self, obj):
        return format_html(
            "<details><summary>原始 AI JSON（排查用）</summary>"
            '<pre style="white-space: pre-wrap; word-break: break-word; margin-top: 8px;">{}</pre>'
            "</details>",
            _pretty_json(obj.ai_structured_json),
        )

    @admin.display(description="AI同步告警")
    def ai_sync_warnings_display(self, obj):
        return format_html(
            '<pre style="white-space: pre-wrap; word-break: break-word; margin: 0;">{}</pre>',
            _pretty_json(obj.ai_sync_warnings),
        )

    @admin.display(description="当前生效来源")
    def effective_structured_source(self, obj):
        source = obj.get_effective_structured_json_source()
        if source == "REVIEWED":
            return "人工修订"
        if source == "AI":
            return "原始 AI"
        return "-"

    @admin.action(description="提交 AI 解析任务")
    def enqueue_ai_extraction(self, request, queryset):
        from ai_vision.tasks import extract_report_image_task

        count = 0
        for image_id in queryset.values_list("id", flat=True):
            extract_report_image_task.delay(image_id)
            count += 1
        self.message_user(request, f"已提交 {count} 张图片的 AI 解析任务。", messages.SUCCESS)

    def has_add_permission(self, request):
        return False

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        obj = self.get_object(request, object_id) if object_id else None
        if request.method == "POST" and obj and "_clear_reviewed_json" in request.POST:
            obj.reviewed_structured_json = None
            obj.reviewed_by = None
            obj.reviewed_at = None
            obj.save(update_fields=["reviewed_structured_json", "reviewed_by", "reviewed_at"])
            stats = rebuild_report_image_structured_results(obj)
            self.log_change(request, obj, "清空人工修订结果")
            self._message_sync_result(request, stats, prefix="已清空人工修订，")
            return HttpResponseRedirect(request.path)

        extra_context = extra_context or {}
        extra_context["show_review_clear_button"] = bool(obj and isinstance(obj.reviewed_structured_json, dict))
        extra_context["review_item_abnormal_choices"] = ABNORMAL_FLAG_CHOICES
        review_item_statuses = analyze_report_image_structured_items(obj) if obj else []
        extra_context["review_item_statuses"] = review_item_statuses
        extra_context["review_item_statuses_json"] = json.dumps(review_item_statuses, ensure_ascii=False)
        extra_context["report_image_url"] = obj.image_url if obj and obj.image_url else ""
        extra_context["report_image_alt"] = f"报告图片 #{obj.pk}" if obj else "报告图片"
        return super().changeform_view(request, object_id, form_url, extra_context)

    def save_model(self, request, obj, form, change):
        obj.reviewed_structured_json = form.cleaned_data["reviewed_structured_payload"]
        obj.reviewed_by = request.user
        obj.reviewed_at = timezone.now()
        obj.save(update_fields=["reviewed_structured_json", "reviewed_by", "reviewed_at"])
        stats = rebuild_report_image_structured_results(obj)
        self._message_sync_result(request, stats, prefix="已保存人工修订，")

    def _message_sync_result(self, request, stats, *, prefix: str) -> None:
        status = stats.get("status")
        if status == "synced":
            self.message_user(
                request,
                f"{prefix}已重建 {stats.get('created_or_updated', 0)} 条正式结果，{stats.get('orphans', 0)} 条孤儿字段。",
                messages.SUCCESS,
            )
            return

        if status == "warning_blocked":
            warning_messages = []
            for warning in (stats.get("warnings") or {}).values():
                if isinstance(warning, dict):
                    warning_messages.append(str(warning.get("message") or "").strip())
            detail = "；".join(filter(None, warning_messages)) or "存在待处理告警。"
            self.message_user(request, f"{prefix}但因告警阻断未同步：{detail}", messages.WARNING)
            return

        reason = str(stats.get("reason") or "未知原因")
        self.message_user(request, f"{prefix}但未同步：{reason}", messages.WARNING)
