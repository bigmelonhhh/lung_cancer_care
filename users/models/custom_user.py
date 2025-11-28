import uuid

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models

from users import choices
from users.managers import CustomUserManager
from users.models.base import TimeStampedModel
from typing import Optional


def _generate_username() -> str:
    """
    【业务说明】默认账号需要一个系统唯一的用户名，便于 Django 认证体系工作。
    【用法】无需显式调用，字段 default 自动触发。
    【使用示例】返回值形如 `user_f12ab34cd56ef7890`。
    【参数】无。
    【返回值】str 类型的唯一用户名。
    """

    return f"user_{uuid.uuid4().hex[:20]}"


class CustomUser(TimeStampedModel, AbstractBaseUser, PermissionsMixin):
    """
    【业务说明】封装平台所有登录入口（患者、医生、销售、助理、管理员），并与各 Profile 解耦。
    【用法】通过 Django 认证体系创建与登录，配合各 Profile 完成业务操作。
    【使用示例】使用 `CustomUser.objects.create_user(user_type=choices.UserType.SALES, phone="13800138000")` 创建销售账号。
    【参数】字段详见下方定义。
    【返回值】标准 Django 用户对象，可在 Session、Permission 场景复用。
    """

    username = models.CharField(
        "系统用户名",
        max_length=150,
        unique=True,
        default=_generate_username,
        help_text="【业务说明】认证体系主键；【用法】系统自动生成；【示例】user_abcd1234;【参数】无；【返回值】str",
    )
    phone = models.CharField(
        "登录手机号",
        max_length=15,
        unique=True,
        null=True,
        blank=True,
        help_text="【业务说明】非患者账号的主要登录凭据；【用法】医生/销售/助理需填写；【示例】13800138000;【参数】字符串;【返回值】str",
    )

    wx_openid = models.CharField(
        "微信 OpenID",
        max_length=64,
        unique=True,
        null=True,
        blank=True,
        help_text="【业务说明】C 端患者/家属绑定的 OpenID；【用法】仅 user_type=1 需要；【示例】oUpF80Mh3VQW...;【参数】str;【返回值】str",
    )
    wx_unionid = models.CharField(
        "微信 UnionID",
        max_length=64,
        unique=True,
        null=True,
        blank=True,
        help_text="【业务说明】多应用打通的 UnionID；【用法】用于后续拓展；【示例】ou123456789;【参数】str;【返回值】str",
    )
    wx_nickname = models.CharField(
        "微信昵称",
        max_length=64,
        blank=True,
        help_text="【业务说明】展示在聊天、工作室等场景的昵称；【用法】同步微信昵称或人工录入；【示例】张同学;【参数】str;【返回值】str",
    )
    wx_avatar_url = models.URLField(
        "头像 URL",
        max_length=500,
        blank=True,
        help_text="【业务说明】头像 URL；【用法】前端直接展示；【示例】https://example.com/avatar.png;【参数】URL 字符串;【返回值】str",
    )
    is_subscribe = models.BooleanField(
        "是否关注公众号",
        default=False,
        help_text="【业务说明】记录是否关注公众号；【用法】用于模板消息推送判断；【示例】True;【参数】bool;【返回值】bool",
    )

    user_type = models.PositiveSmallIntegerField(
        "用户类型",
        choices=choices.UserType.choices,
        default=choices.UserType.PATIENT,
        help_text="【业务说明】划分账号角色；【用法】创建时指定；【示例】用户类型=医生；【参数】整数枚举；【返回值】int",
    )
    is_active = models.BooleanField(
        "是否启用",
        default=True,
        help_text="【业务说明】控制账号启用状态；【用法】禁用违规用户；【示例】False 表示冻结；【参数】bool;【返回值】bool",
    )
    is_staff = models.BooleanField(
        "后台权限",
        default=False,
        help_text="【业务说明】标识后台可登录管理员站点；【用法】授予运营或管理员；【示例】True;【参数】bool;【返回值】bool",
    )
    date_joined = models.DateTimeField(
        "注册时间",
        auto_now_add=True,
        help_text="【业务说明】账号注册时间；【用法】统计新增；【示例】2025-01-01 10:00;【参数】无;【返回值】datetime",
    )
    bound_sales = models.ForeignKey(
        "users.SalesProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="leads",
        verbose_name="潜客归属销售",
        help_text="【业务说明】记录未建档潜客归属；【用法】销售跟进；【示例】SalesProfile#1；【参数】外键；【返回值】SalesProfile",
    )

    objects = CustomUserManager()

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        verbose_name = "Custom User"
        verbose_name_plural = "Custom Users"

    def clean(self):
        """
        【业务说明】在保存前校验不同 user_type 的登录凭据满足规范。
        【用法】Django ORM 自动调用，也可手动 `full_clean()` 触发。
        【参数】self：当前用户实例。
        【返回值】None，若校验失败抛出 ValidationError。
        【使用示例】`user.full_clean()`，当患者缺失 wx_openid 会抛错。
        """

        super().clean()
        if self.user_type == choices.UserType.PATIENT:
            if not self.wx_openid:
                raise ValidationError({"wx_openid": "患者/家属必须绑定 wx_openid。"})
        else:
            if not self.phone:
                raise ValidationError({"phone": "非患者类账号必须填写登录手机号。"})

    def __str__(self) -> str:
        """
        【业务说明】统一对象的可读展示，用于 admin、日志等。
        【用法】print(user) 或管理后台展示。
        【参数】self：当前对象。
        【返回值】str，包含昵称与角色。
        【使用示例】`str(user)` -> `张三(主治医生)`。
        """

        base = self.wx_nickname or self.username
        return f"{base}({self.get_user_type_display()})"

    @property
    def display_name(self) -> str:
        """
        【业务说明】聊天、推送等场景需要的友好称呼。
        【用法】`user.display_name` 直接读取。
        【参数】无。
        【返回值】str，优先昵称否则用户名。
        【使用示例】患者未设置昵称时返回 `user_xxx`。
        """

        return self.wx_nickname or self.username


class PlatformAdminUserManager(CustomUserManager):
    """Manager that restricts queryset to platform administrators."""

    def get_queryset(self):  # pragma: no cover - simple override
        return super().get_queryset().filter(user_type=choices.UserType.ADMIN)


class PlatformAdminUser(CustomUser):
    """Proxy model for managing platform administrators in Django admin."""

    objects = PlatformAdminUserManager()

    class Meta:
        proxy = True
        verbose_name = "平台管理员"
        verbose_name_plural = "平台管理员"
