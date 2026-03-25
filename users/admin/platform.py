"""Platform admin proxy management."""

from django import forms
from django.contrib import admin
from django.db import transaction

from users import choices
from users.models import CustomUser, PlatformAdminUser


class PlatformAdminCreationForm(forms.ModelForm):
    """
    平台管理员-创建表单
    """
    username = forms.CharField(label="用户名")
    phone = forms.CharField(label="登录手机号")
    name = forms.CharField(label="管理员姓名")
    password = forms.CharField(label="初始密码", widget=forms.PasswordInput)

    class Meta:
        model = PlatformAdminUser
        fields = [
            "username",
            "phone",
            "wx_nickname",
            "is_staff",      # 【新增】后台登录权限
            "is_superuser",
            "is_active",
            "groups",
            "user_permissions",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 强制指定创建出的用户类型为管理员
        self.instance.user_type = choices.UserType.ADMIN
        self.instance.wx_openid = None
        self.instance.wx_unionid = None
        # 创建时默认勾选“后台登录权限”
        self.fields["is_staff"].initial = True

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
        user = super().save(commit=False)
        user.username = self.cleaned_data["username"]
        user.phone = self.cleaned_data["phone"]
        user.wx_nickname = self.cleaned_data["name"]
        user.wx_openid = None
        user.wx_unionid = None
        user.user_type = choices.UserType.ADMIN
        user.is_active = self.cleaned_data.get("is_active", True)
        user.is_staff = self.cleaned_data.get("is_staff", True)
        user.is_superuser = self.cleaned_data.get("is_superuser", False)
        user.set_password(self.cleaned_data["password"])

        if commit:
            with transaction.atomic():
                user.save()
                self._save_m2m()

        return user

    def save_m2m(self):
        """Admin 在 save_related 阶段会调用，创建表单需显式提供该协议。"""
        self._save_m2m()


class PlatformAdminChangeForm(forms.ModelForm):
    """
    平台管理员-修改表单
    """
    username = forms.CharField(label="用户名")
    phone = forms.CharField(label="登录手机号")
    name = forms.CharField(label="管理员姓名")
    
    reset_password = forms.CharField(
        label="重置密码", 
        required=False, 
        widget=forms.PasswordInput, 
        help_text="留空表示不修改密码"
    )

    class Meta:
        model = PlatformAdminUser
        fields = [
            "username",
            "phone",
            "wx_nickname",
            "is_active",
            "is_staff",      # 【新增】
            "is_superuser",
            "groups",
            "user_permissions",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance:
            self.fields["username"].initial = self.instance.username
            self.fields["phone"].initial = self.instance.phone
            self.fields["name"].initial = self.instance.wx_nickname
            self.fields["is_active"].initial = self.instance.is_active
            self.fields["is_staff"].initial = self.instance.is_staff # 【新增】回显

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        # 修改时，排除自己
        qs = CustomUser.objects.filter(username=username)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("该用户名已存在")
        return username

    def clean_phone(self):
        phone = self.cleaned_data["phone"].strip()
        # 修改时，排除自己
        qs = CustomUser.objects.filter(phone=phone)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("该手机号已被其他账号使用")
        return phone

    def save(self, commit=True):
        # 先调用父类 save(commit=False) 获取实例
        user = super().save(commit=False)
        
        # 1. 赋值常规字段
        user.username = self.cleaned_data["username"]
        user.phone = self.cleaned_data["phone"]
        user.wx_nickname = self.cleaned_data["name"]
        user.is_active = self.cleaned_data.get("is_active", True)
        user.is_staff = self.cleaned_data.get("is_staff", True) # 【新增】保存权限状态
        user.is_superuser = self.cleaned_data.get("is_superuser", False)
        
        # 2. 处理密码
        new_password = self.cleaned_data.get("reset_password")
        if new_password:
            user.set_password(new_password)

        # 3. 显式保存到数据库
        if commit:
            with transaction.atomic():
                update_fields = [
                    "username", "phone", "wx_nickname", 
                    "is_active", "is_staff", "is_superuser" # 【新增】is_staff
                ]
                if new_password:
                    update_fields.append("password")
                
                user.save(update_fields=update_fields)
                
                # 4. 保存 M2M (权限组)
                self.save_m2m()
                
        return user


@admin.register(PlatformAdminUser)
class PlatformAdminUserAdmin(admin.ModelAdmin):
    # 【修改】列表页增加 is_staff 展示
    list_display = ("username", "wx_nickname", "phone", "is_active", "is_staff", "date_joined", "is_superuser", "get_groups")
    search_fields = ("username", "wx_nickname", "phone")
    
    # 只读字段去掉了 'username'
    readonly_fields = ("date_joined", "user_type")
    
    filter_horizontal = ("groups", "user_permissions")
    actions = ["disable_admins"]

    def get_form(self, request, obj=None, **kwargs):
        kwargs["form"] = PlatformAdminChangeForm if obj else PlatformAdminCreationForm
        return super().get_form(request, obj, **kwargs)

    def get_queryset(self, request):
        return super().get_queryset(request).filter(user_type=choices.UserType.ADMIN)

    def has_delete_permission(self, request, obj=None):
        return True 

    def get_fieldsets(self, request, obj=None):
        if obj:
            # 修改页
            return (
                ("基础信息", {"fields": ("username", "name", "phone", "reset_password")}),
                (
                    "权限与分组",
                    {
                        # 【修改】这里加上 is_staff
                        "fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions"),
                    },
                ),
                ("其他信息", {"fields": ("date_joined", "user_type")}),
            )
        # 创建页
        return (
            ("基础信息", {"fields": ("username", "name", "phone", "password")}),
            (
                "权限与分组",
                {
                    # 【修改】这里加上 is_staff
                    "fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions"),
                },
            ),
        )

    @admin.action(description="禁用所选管理员")
    def disable_admins(self, request, queryset):
        count = queryset.update(is_active=False)
        self.message_user(request, f"已禁用 {count} 个管理员。")

    def get_groups(self, obj):
        return ", ".join(obj.groups.values_list("name", flat=True)) or "-"

    get_groups.short_description = "所属用户组"
