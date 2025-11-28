from django.core.exceptions import ValidationError
from django.db import models

from users import choices
from users.models.base import TimeStampedModel


class SalesProfile(TimeStampedModel):
    """
    【业务说明】记录销售专员的组织信息与统计指标，用于渠道管理与绩效核算。
    【用法】在销售创建账号后补全档案，后续用于医生绑定与业绩计算。
    【使用示例】`SalesProfile.objects.create(user=user, name="李业务")`。
    【参数】字段定义见下；继承时间戳。
    【返回值】Model 实例。
    """

    user = models.OneToOneField(
        "users.CustomUser",
        on_delete=models.CASCADE,
        related_name="sales_profile",
        verbose_name="销售账号",
        help_text="【业务说明】关联基础账号；【用法】user_type 必须为销售；【示例】CustomUser#20；【参数】外键；【返回值】CustomUser",
    )
    name = models.CharField(
        "销售姓名",
        max_length=50,
        help_text="【业务说明】销售真实姓名；【用法】对外展示；【示例】李业务；【参数】str；【返回值】str",
    )
    region = models.CharField(
        "负责区域",
        max_length=100,
        blank=True,
        help_text="【业务说明】负责区域，如华东；【用法】用于统计；【示例】华东大区；【参数】str；【返回值】str",
    )
    invite_code = models.CharField(
        "专属邀请码",
        max_length=20,
        unique=True,
        null=True,
        blank=True,
        help_text="【业务说明】专属邀请码，用于医生或患者绑定；【用法】可选；【示例】BD2024AB；【参数】str；【返回值】str",
    )
    qrcode_url = models.URLField(
        "永久二维码",
        blank=True,
        help_text="【业务说明】微信永久二维码链接；【用法】缓存以减少 API 调用",
    )
    managed_doctor_count = models.PositiveIntegerField(
        "医生数量",
        default=0,
        help_text="【业务说明】冗余统计字段，表示目前维护的医生数；【用法】通过定时任务刷新；【示例】5；【参数】int；【返回值】int",
    )
    managed_patient_count = models.PositiveIntegerField(
        "患者数量",
        default=0,
        help_text="【业务说明】冗余统计字段，表示名下患者数；【用法】报表展示；【示例】120；【参数】int；【返回值】int",
    )

    class Meta:
        verbose_name = "销售档案"
        verbose_name_plural = "销售档案"

    def clean(self):
        """
        【业务说明】确保档案只绑定销售类型账号。
        【用法】保存前自动调用。
        【参数】self。
        【返回值】None，违规抛错。
        【使用示例】`profile.full_clean()`。
        """

        super().clean()
        if not self.user_id:
            return
        if self.user.user_type != choices.UserType.SALES:
            raise ValidationError("关联账号必须是销售类型。")

    def __str__(self) -> str:
        """
        【业务说明】在 admin/日志中展示销售简要信息。
        【用法】`str(profile)`。
        【参数】self。
        【返回值】str，例如“李业务(20)”。
        【使用示例】控制台输出。
        """

        return f"{self.name}({self.user_id})"
