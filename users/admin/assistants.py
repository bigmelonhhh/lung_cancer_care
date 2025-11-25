"""Assistant admin configuration."""

import random
import string

from django import forms
from django.contrib import admin
from django.contrib.admin.widgets import FilteredSelectMultiple
from django.db import transaction

from users import choices
from users.models import AssistantProfile, CustomUser, DoctorAssistantMap, DoctorProfile


class AssistantDoctorMixin(forms.ModelForm):
    doctors = forms.ModelMultipleChoiceField(
        label="负责医生",
        required=False,
        queryset=DoctorProfile.objects.select_related("user").filter(user__is_active=True),
        widget=FilteredSelectMultiple("负责医生", is_stacked=False),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["doctors"].initial = self.instance.doctors.values_list("pk", flat=True)

    def _sync_doctors(self, instance, selected_doctors):
        current = set(instance.doctors.values_list("pk", flat=True))
        selected = set(selected_doctors.values_list("pk", flat=True))
        to_add = selected - current
        to_remove = current - selected
        if to_add:
            DoctorAssistantMap.objects.bulk_create(
                [
                    DoctorAssistantMap(assistant=instance, doctor_id=doctor_id)
                    for doctor_id in to_add
                ],
                ignore_conflicts=True,
            )
        if to_remove:
            DoctorAssistantMap.objects.filter(
                assistant=instance, doctor_id__in=to_remove
            ).delete()

    def save(self, commit=True):
        instance = super().save(commit)
        if instance.pk:
            selected = self.cleaned_data.get("doctors", self.fields["doctors"].queryset.none())
            self._sync_doctors(instance, selected)
        return instance


class AssistantCreationForm(AssistantDoctorMixin):
    phone = forms.CharField(label="登录手机号")
    password = forms.CharField(label="初始密码", widget=forms.PasswordInput)

    class Meta:
        model = AssistantProfile
        fields = ["name", "status", "work_phone", "joined_at"]

    def clean_phone(self):
        phone = self.cleaned_data["phone"].strip()
        if CustomUser.objects.filter(phone=phone).exists():
            raise forms.ValidationError("该手机号已被其他账号使用")
        return phone

    def _generate_username(self, phone: str) -> str:
        base = f"assistant_{phone}"
        if not CustomUser.objects.filter(username=base).exists():
            return base
        suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
        return f"{base}_{suffix}"

    def save(self, commit=True):
        phone = self.cleaned_data["phone"]
        password = self.cleaned_data["password"]
        with transaction.atomic():
            username = self._generate_username(phone)
            user = CustomUser(
                username=username,
                phone=phone,
                user_type=choices.UserType.ASSISTANT,
                is_active=True,
                is_staff=False,
            )
            user.set_password(password)
            user.save()

            profile = super().save(commit=False)
            profile.user = user
            if commit:
                profile.save()
        self._sync_doctors(profile, self.cleaned_data.get("doctors", self.fields["doctors"].queryset.none()))
        return profile


class AssistantChangeForm(AssistantDoctorMixin):
    phone = forms.CharField(label="登录手机号")
    is_active = forms.BooleanField(label="账号启用", required=False)
    reset_password = forms.CharField(
        label="重置密码",
        required=False,
        widget=forms.PasswordInput,
        help_text="留空表示不修改密码",
    )

    class Meta:
        model = AssistantProfile
        fields = ["name", "status", "work_phone", "joined_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.user:
            self.fields["phone"].initial = self.instance.user.phone
            self.fields["is_active"].initial = self.instance.user.is_active

    def clean_phone(self):
        phone = self.cleaned_data["phone"].strip()
        user_qs = CustomUser.objects.filter(phone=phone)
        if self.instance and self.instance.user_id:
            user_qs = user_qs.exclude(id=self.instance.user_id)
        if user_qs.exists():
            raise forms.ValidationError("该手机号已被其他账号使用")
        return phone

    def save(self, commit=True):
        profile = super().save(commit=False)
        user = profile.user
        user.phone = self.cleaned_data["phone"]
        user.is_active = self.cleaned_data.get("is_active", True)
        new_password = self.cleaned_data.get("reset_password")
        with transaction.atomic():
            if new_password:
                user.set_password(new_password)
            update_fields = ["phone", "is_active"]
            if new_password:
                update_fields.append("password")
            user.save(update_fields=update_fields)
            if commit:
                profile.save()
        return profile


@admin.register(AssistantProfile)
class AssistantProfileAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "user_phone",
        "status",
        "work_phone",
        "joined_at",
        "doctor_count",
        "user_is_active",
    )
    search_fields = ("name", "user__phone")
    list_filter = ("status", ("joined_at", admin.DateFieldListFilter))
    readonly_fields = ("user_username", "user_joined", "user_type_display")
    actions = ["disable_assistants"]

    def get_form(self, request, obj=None, **kwargs):
        kwargs["form"] = AssistantChangeForm if obj else AssistantCreationForm
        return super().get_form(request, obj, **kwargs)

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return self.readonly_fields
        return ()

    def get_fieldsets(self, request, obj=None):
        if obj:
            return (
                ("账号信息", {"fields": ("phone", "is_active", "reset_password")}),
                ("档案信息", {"fields": ("name", "status", "work_phone", "joined_at")}),
                ("负责医生", {"fields": ("doctors",)}),
                ("只读信息", {"fields": self.readonly_fields}),
            )
        return (
            ("账号信息", {"fields": ("phone", "password")}),
            ("档案信息", {"fields": ("name", "status", "work_phone", "joined_at")}),
            ("负责医生", {"fields": ("doctors",)}),
        )

    def user_phone(self, obj):
        return obj.user.phone

    user_phone.short_description = "手机号"

    def user_is_active(self, obj):
        return obj.user.is_active

    user_is_active.boolean = True
    user_is_active.short_description = "账号状态"

    def user_joined(self, obj):
        return obj.user.date_joined

    user_joined.short_description = "注册时间"

    def user_username(self, obj):
        return obj.user.username

    user_username.short_description = "用户名"

    def user_type_display(self, obj):
        return obj.user.get_user_type_display()

    user_type_display.short_description = "用户类型"

    def doctor_count(self, obj):
        return obj.doctors.count()

    doctor_count.short_description = "关联医生数"

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="禁用所选助理")
    def disable_assistants(self, request, queryset):
        for profile in queryset.select_related("user"):
            profile.user.is_active = False
            profile.status = choices.AssistantStatus.INACTIVE
            profile.user.save(update_fields=["is_active"])
            profile.save(update_fields=["status"])
        self.message_user(request, "已禁用所选助理。")
