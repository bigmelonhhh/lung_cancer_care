"""Platform admin proxy management."""

import random
import string

from django import forms
from django.contrib import admin
from django.db import transaction

from users import choices
from users.models import CustomUser, PlatformAdminUser


class PlatformAdminCreationForm(forms.ModelForm):
    username = forms.CharField(label="用户名")
    phone = forms.CharField(label="登录手机号")
    password = forms.CharField(label="初始密码", widget=forms.PasswordInput)
    name = forms.CharField(label="管理员姓名")

    class Meta:
        model = PlatformAdminUser
        fields = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # ensure validation treats this as platform admin
        self.instance.user_type = choices.UserType.ADMIN
        self.instance.wx_openid = None
        self.instance.wx_unionid = None

    def clean_phone(self):
        phone = self.cleaned_data["phone"].strip()
        if CustomUser.objects.filter(phone=phone).exists():
            raise forms.ValidationError("该手机号已被其他账号使用")
        return phone

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if CustomUser.objects.filter(username=username).exists():
            raise forms.ValidationError("该用户名已存在")
        return username

    def save(self, commit=True):
        username = self.cleaned_data["username"]
        phone = self.cleaned_data["phone"]
        password = self.cleaned_data["password"]
        name = self.cleaned_data["name"]
        with transaction.atomic():
            user = PlatformAdminUser(
                username=username,
                phone=phone,
                wx_nickname=name,
                wx_openid=None,
                wx_unionid=None,
                user_type=choices.UserType.ADMIN,
                is_active=True,
                is_staff=True,
                is_superuser=True,
            )
            user.set_password(password)
            user.save()
        return user


class PlatformAdminChangeForm(forms.ModelForm):
    phone = forms.CharField(label="登录手机号")
    name = forms.CharField(label="管理员姓名")
    is_active = forms.BooleanField(label="账号启用", required=False)
    reset_password = forms.CharField(
        label="重置密码",
        required=False,
        widget=forms.PasswordInput,
        help_text="留空表示不修改密码",
    )

    class Meta:
        model = PlatformAdminUser
        fields = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance:
            self.fields["phone"].initial = self.instance.phone
            self.fields["name"].initial = self.instance.wx_nickname
            self.fields["is_active"].initial = self.instance.is_active

    def clean_phone(self):
        phone = self.cleaned_data["phone"].strip()
        qs = CustomUser.objects.filter(phone=phone)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("该手机号已被其他账号使用")
        return phone

    def save(self, commit=True):
        user = super().save(commit=False)
        user.phone = self.cleaned_data["phone"]
        user.wx_nickname = self.cleaned_data["name"]
        user.wx_openid = None
        user.wx_unionid = None
        user.is_active = self.cleaned_data.get("is_active", True)
        new_password = self.cleaned_data.get("reset_password")
        with transaction.atomic():
            if new_password:
                user.set_password(new_password)
            update_fields = ["phone", "wx_nickname", "is_active"]
            if new_password:
                update_fields.append("password")
            user.save(update_fields=update_fields)
        return user


@admin.register(PlatformAdminUser)
class PlatformAdminUserAdmin(admin.ModelAdmin):
    list_display = ("username", "wx_nickname", "phone", "is_active", "date_joined", "is_superuser")
    search_fields = ("username", "wx_nickname", "phone")
    readonly_fields = ("username", "date_joined", "user_type", "is_staff", "is_superuser")
    actions = ["disable_admins"]

    def get_form(self, request, obj=None, **kwargs):
        kwargs["form"] = PlatformAdminChangeForm if obj else PlatformAdminCreationForm
        return super().get_form(request, obj, **kwargs)

    def get_queryset(self, request):
        return super().get_queryset(request).filter(user_type=choices.UserType.ADMIN)

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return self.readonly_fields
        return ()

    @admin.action(description="禁用所选管理员")
    def disable_admins(self, request, queryset):
        count = queryset.update(is_active=False)
        self.message_user(request, f"已禁用 {count} 个管理员。")
