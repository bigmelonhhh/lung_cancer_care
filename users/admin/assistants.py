"""Assistant admin configuration."""

import random
import string

from django import forms
from django.contrib import admin
from django.db import transaction

from users import choices
from users.models import AssistantProfile, CustomUser, DoctorAssistantMap, DoctorProfile


class AssistantCreationForm(forms.ModelForm):
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
        return profile


class AssistantChangeForm(forms.ModelForm):
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


class DoctorAssistantInline(admin.TabularInline):
    model = DoctorAssistantMap
    fk_name = "assistant"
    extra = 1

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "doctor":
            kwargs["queryset"] = DoctorProfile.objects.select_related("user").filter(user__is_active=True)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


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
    inlines = [DoctorAssistantInline]
    actions = ["disable_assistants"]

    def get_form(self, request, obj=None, **kwargs):
        kwargs["form"] = AssistantChangeForm if obj else AssistantCreationForm
        return super().get_form(request, obj, **kwargs)

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return self.readonly_fields
        return ()

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
