"""Admin for structured checkup master data."""

from django import forms
from django.contrib import admin, messages
from django.forms.models import BaseInlineFormSet

from core.models import CheckupFieldMapping, StandardField, StandardFieldAlias
from core.utils.normalization import normalize_standard_field_name


def _standard_field_display(standard_field: StandardField) -> str:
    return f"{standard_field.chinese_name}（{standard_field.local_code}）"


def _find_duplicate_standard_field(
    normalized_name: str,
    *,
    exclude_standard_field_id: int | None = None,
) -> StandardField | None:
    standard_fields = StandardField.objects.all()
    if exclude_standard_field_id:
        standard_fields = standard_fields.exclude(pk=exclude_standard_field_id)

    for standard_field in standard_fields.only("id", "local_code", "chinese_name"):
        if normalize_standard_field_name(standard_field.chinese_name) == normalized_name:
            return standard_field
    return None


def _find_duplicate_alias(
    normalized_name: str,
    *,
    exclude_alias_id: int | None = None,
    exclude_standard_field_id: int | None = None,
) -> StandardFieldAlias | None:
    duplicate_aliases = StandardFieldAlias.objects.filter(normalized_name=normalized_name)
    if exclude_alias_id:
        duplicate_aliases = duplicate_aliases.exclude(pk=exclude_alias_id)
    if exclude_standard_field_id:
        duplicate_aliases = duplicate_aliases.exclude(standard_field_id=exclude_standard_field_id)
    return duplicate_aliases.select_related("standard_field").first()


def _duplicate_standard_field_message(normalized_name: str, standard_field: StandardField) -> str:
    return (
        f"归一化后名称“{normalized_name}”已存在，"
        f"已有标准字段“{_standard_field_display(standard_field)}”。"
        "系统会忽略括号、连字符等符号后查重。"
    )


def _duplicate_alias_message(normalized_name: str, alias: StandardFieldAlias) -> str:
    return (
        f"归一化后名称“{normalized_name}”已存在，"
        f"已有别名“{alias.alias_name}”对应标准字段“{_standard_field_display(alias.standard_field)}”。"
        "系统会忽略括号、连字符等符号后查重。"
    )


class StandardFieldAdminForm(forms.ModelForm):
    class Meta:
        model = StandardField
        fields = "__all__"

    def clean_chinese_name(self):
        chinese_name = self.cleaned_data["chinese_name"]
        normalized_name = normalize_standard_field_name(chinese_name)
        if not normalized_name:
            raise forms.ValidationError("中文标准名归一化后为空，请填写可识别的字段名称。")

        duplicate_field = _find_duplicate_standard_field(
            normalized_name=normalized_name,
            exclude_standard_field_id=self.instance.pk,
        )
        if duplicate_field:
            raise forms.ValidationError(_duplicate_standard_field_message(normalized_name, duplicate_field))

        duplicate_alias = _find_duplicate_alias(
            normalized_name,
            exclude_standard_field_id=self.instance.pk,
        )
        if duplicate_alias:
            raise forms.ValidationError(_duplicate_alias_message(normalized_name, duplicate_alias))

        return chinese_name


class StandardFieldAliasAdminForm(forms.ModelForm):
    class Meta:
        model = StandardFieldAlias
        fields = "__all__"

    def clean_alias_name(self):
        alias_name = self.cleaned_data["alias_name"]
        normalized_name = normalize_standard_field_name(alias_name)
        if not normalized_name:
            raise forms.ValidationError("别名归一化后为空，请填写可识别的字段名称。")

        return alias_name

    def clean(self):
        cleaned_data = super().clean()
        alias_name = cleaned_data.get("alias_name")
        if not alias_name:
            return cleaned_data

        normalized_name = normalize_standard_field_name(alias_name)
        if not normalized_name:
            return cleaned_data

        standard_field = cleaned_data.get("standard_field") or getattr(self.instance, "standard_field", None)
        standard_field_id = getattr(standard_field, "pk", None) or getattr(self.instance, "standard_field_id", None)

        duplicate_alias = _find_duplicate_alias(
            normalized_name,
            exclude_alias_id=self.instance.pk,
        )
        if duplicate_alias:
            self.add_error("alias_name", _duplicate_alias_message(normalized_name, duplicate_alias))
            return cleaned_data

        duplicate_field = _find_duplicate_standard_field(
            normalized_name,
            exclude_standard_field_id=standard_field_id,
        )
        if duplicate_field:
            self.add_error("alias_name", _duplicate_standard_field_message(normalized_name, duplicate_field))

        return cleaned_data


class StandardFieldAliasInlineFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()

        normalized_aliases: dict[str, str] = {}
        for form in self.forms:
            cleaned_data = getattr(form, "cleaned_data", {})
            if not cleaned_data or cleaned_data.get("DELETE"):
                continue

            alias_name = cleaned_data.get("alias_name")
            if not alias_name:
                continue

            normalized_name = normalize_standard_field_name(alias_name)
            previous_alias_name = normalized_aliases.get(normalized_name)
            if previous_alias_name:
                raise forms.ValidationError(
                    f"本次提交中存在归一化后重复的别名“{normalized_name}”："
                    f"“{previous_alias_name}”和“{alias_name}”。"
                )

            normalized_aliases[normalized_name] = alias_name


class StandardFieldAliasInline(admin.TabularInline):
    model = StandardFieldAlias
    form = StandardFieldAliasAdminForm
    formset = StandardFieldAliasInlineFormSet
    extra = 0
    fields = ("alias_name", "normalized_name", "is_active", "notes")
    readonly_fields = ("normalized_name",)
    ordering = ("alias_name", "id")


class CheckupFieldMappingInlineForField(admin.TabularInline):
    model = CheckupFieldMapping
    extra = 0
    fields = ("checkup_item", "sort_order", "is_active")
    autocomplete_fields = ("checkup_item",)
    ordering = ("sort_order", "id")


@admin.register(StandardField)
class StandardFieldAdmin(admin.ModelAdmin):
    form = StandardFieldAdminForm
    list_display = (
        "local_code",
        "chinese_name",
        "english_abbr",
        "value_type",
        "default_unit",
        "is_active",
        "sort_order",
    )
    list_editable = ("sort_order",)
    search_fields = ("local_code", "chinese_name", "english_abbr")
    list_filter = ("value_type", "is_active")
    ordering = ("sort_order", "local_code")
    actions = ("mark_active", "mark_inactive")
    inlines = [StandardFieldAliasInline, CheckupFieldMappingInlineForField]

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions

    @admin.action(description="标记为启用")
    def mark_active(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"已启用 {updated} 个标准字段。", messages.SUCCESS)

    @admin.action(description="标记为停用")
    def mark_inactive(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"已停用 {updated} 个标准字段。", messages.SUCCESS)


@admin.register(StandardFieldAlias)
class StandardFieldAliasAdmin(admin.ModelAdmin):
    form = StandardFieldAliasAdminForm
    list_display = ("alias_name", "normalized_name", "standard_field", "is_active")
    search_fields = (
        "alias_name",
        "normalized_name",
        "standard_field__chinese_name",
        "standard_field__local_code",
    )
    list_filter = ("is_active",)
    ordering = ("alias_name", "id")
    autocomplete_fields = ("standard_field",)
    readonly_fields = ("normalized_name",)
    actions = ("mark_active", "mark_inactive", "reprocess_related_orphans")

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions

    @admin.action(description="标记为启用")
    def mark_active(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"已启用 {updated} 个字段别名。", messages.SUCCESS)

    @admin.action(description="标记为停用")
    def mark_inactive(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"已停用 {updated} 个字段别名。", messages.SUCCESS)

    @admin.action(description="重跑受影响孤儿")
    def reprocess_related_orphans(self, request, queryset):
        from health_data.tasks import reprocess_orphan_fields_task

        normalized_names = list(queryset.values_list("normalized_name", flat=True))
        if normalized_names:
            reprocess_orphan_fields_task.delay(normalized_names=normalized_names)
        self.message_user(request, f"已提交 {len(normalized_names)} 个别名相关孤儿的异步重跑任务。", messages.SUCCESS)
