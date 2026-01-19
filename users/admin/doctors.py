"""Doctor admin configuration."""

import random
import string
import uuid

from django import forms
from django.contrib import admin, messages
from django.db import transaction
from django.shortcuts import redirect, get_object_or_404
from django.urls import path, reverse
from django.utils.html import format_html

from users import choices
from users.models import CustomUser, DoctorProfile, SalesProfile, DoctorStudio


class DoctorCreationForm(forms.ModelForm):
    phone = forms.CharField(label="登录手机号")
    password = forms.CharField(label="初始密码", widget=forms.PasswordInput)

    class Meta:
        model = DoctorProfile
        fields = ["name", "hospital", "department", "title", "sales", "studio"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["sales"].queryset = SalesProfile.objects.select_related("user").filter(user__is_active=True)

    def _generate_username(self, phone: str) -> str:
        base = f"doctor_{phone}"
        if not CustomUser.objects.filter(username=base).exists():
            return base
        suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
        return f"{base}_{suffix}"

    def clean_phone(self):
        phone = self.cleaned_data["phone"].strip()
        if CustomUser.objects.filter(phone=phone).exists():
            raise forms.ValidationError("该手机号已被其他账号使用")
        return phone

    def save(self, commit=True):
        phone = self.cleaned_data["phone"]
        password = self.cleaned_data["password"]
        with transaction.atomic():
            username = self._generate_username(phone)
            user = CustomUser(
                username=username,
                phone=phone,
                user_type=choices.UserType.DOCTOR,
                is_active=True,
                is_staff=False,
            )
            user.set_password(password)
            user.save()

            profile = super().save(commit=False)
            profile.user = user
            profile.managed_patient_count = profile.managed_patient_count or 0
            if commit:
                profile.save()
                self.save_m2m()
        return profile


class DoctorChangeForm(forms.ModelForm):
    phone = forms.CharField(label="登录手机号")
    is_active = forms.BooleanField(label="账号启用", required=False)
    reset_password = forms.CharField(
        label="重置密码",
        required=False,
        widget=forms.PasswordInput,
        help_text="留空表示不修改密码",
    )

    class Meta:
        model = DoctorProfile
        fields = ["name", "hospital", "department", "title", "sales", "studio"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["sales"].queryset = SalesProfile.objects.select_related("user").filter(user__is_active=True)
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
                self.save_m2m()
        return profile


@admin.register(DoctorProfile)
class DoctorProfileAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "hospital",
        "department",
        "sales_display",
        "studio_actions",
        "user_phone",
        "user_is_active",
        "user_joined",
    )
    search_fields = ("name", "hospital", "user__phone")
    list_filter = ("sales", "hospital", "user__is_active")
    readonly_fields = (
        "user_username",
        "user_joined",
        "user_type_display",
        "managed_patient_count",
    )
    filter_horizontal = ("sales",)
    actions = ["disable_accounts"]

    def get_form(self, request, obj=None, **kwargs):
        kwargs["form"] = DoctorChangeForm if obj else DoctorCreationForm
        return super().get_form(request, obj, **kwargs)

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return self.readonly_fields
        return ()

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "sales":
            kwargs["queryset"] = SalesProfile.objects.select_related("user").filter(user__is_active=True)
        return super().formfield_for_manytomany(db_field, request, **kwargs)

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

    def sales_display(self, obj):
        names = [sale.name for sale in obj.sales.all()]
        return ", ".join(names) if names else "-"

    sales_display.short_description = "负责销售团队"

    def studio_actions(self, obj):
        if not obj.studio:
            url = reverse("admin:users_doctor_quick_create_studio", args=[obj.pk])
            # 【修改】改为普通的 GET 链接，避免 CSRF 问题
            return format_html(
                '<a class="button" href="{}" style="background-color:#52B45A; color:white; padding:3px 8px; border-radius:4px; font-size:12px;">'
                '⚡️ 一键开通</a>',
                url,
            )
        qrcode_url = reverse("users:studio_qrcode", args=[obj.studio_id])
        studio_change = reverse("admin:users_doctorstudio_change", args=[obj.studio_id])
        return format_html(
            '<a class="button" target="_blank" href="{}" style="background-color:#3B7FDD; color:white; padding:3px 8px; border-radius:4px; font-size:12px; margin-right:5px;">'
            '👀 二维码</a>'
            '<a class="button" href="{}" style="padding:3px 8px; border-radius:4px; font-size:12px;">'
            '✏️ 编辑</a>',
            qrcode_url,
            studio_change,
        )

    studio_actions.short_description = "工作室管理"

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="禁用所选医生账号")
    def disable_accounts(self, request, queryset):
        for profile in queryset.select_related("user"):
            profile.user.is_active = False
            profile.user.save(update_fields=["is_active"])
        self.message_user(request, "已禁用所选医生账号。")

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "quick-create-studio/<int:doctor_id>/",
                self.admin_site.admin_view(self.quick_create_studio),
                name="users_doctor_quick_create_studio",
            )
        ]
        return custom + urls

    def quick_create_studio(self, request, doctor_id):
        # 【业务逻辑】通过 GET 请求快速创建工作室
        doctor = DoctorProfile.objects.filter(pk=doctor_id).select_related("studio").first()
        if not doctor:
            self.message_user(request, "医生不存在", level=messages.ERROR)
            return redirect("admin:users_doctorprofile_changelist")
        
        if doctor.studio:
            self.message_user(request, "该医生已绑定工作室。", level=messages.WARNING)
            return redirect("admin:users_doctorprofile_changelist")

        try:
            with transaction.atomic():
                # 生成随机编码
                for _ in range(5):
                    code = "".join(random.choices(string.digits, k=4))
                    if not DoctorStudio.objects.filter(code=code).exists():
                        break
                else:
                    code = uuid.uuid4().hex[:6] # 兜底

                studio = DoctorStudio.objects.create(
                    name=f"{doctor.name}的工作室",
                    code=code,
                    owner_doctor=doctor,
                )
                doctor.studio = studio
                doctor.save(update_fields=["studio"])
                
            self.message_user(request, f"成功！已创建工作室：{studio.name} (编码 {code})", level=messages.SUCCESS)
        except Exception as e:
            self.message_user(request, f"创建失败：{str(e)}", level=messages.ERROR)

        return redirect("admin:users_doctorprofile_changelist")

