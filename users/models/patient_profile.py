from django.core.exceptions import ValidationError
from django.db import models

from users import choices
from users.models.base import TimeStampedModel


class PatientProfile(TimeStampedModel):
    """
    【业务说明】承载患者全量院外档案，包含联系方式、归属团队及服务状态。
    【用法】销售建档、患者自注册、医生管理等核心流程均读写该模型。
    【使用示例】`PatientProfile.objects.create(phone="13800138000", name="王女士")`。
    【参数】字段定义见下方；继承 TimeStampedModel 自动带有时间戳。
    【返回值】标准 Django Model。
    """

    user = models.OneToOneField(
        "users.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="patient_profile",
        verbose_name="本人账号",
        help_text="【业务说明】患者本人账号；【用法】自注册或认领后绑定；【示例】CustomUser#12；【参数】外键；【返回值】CustomUser",
    )
    phone = models.CharField(
        "患者联系电话",
        max_length=15,
        unique=True,
        help_text="【业务说明】档案唯一锚点；【用法】销售查重或医生联系；【示例】13800138000；【参数】str；【返回值】str",
    )
    name = models.CharField(
        "患者姓名",
        max_length=50,
        default="未命名患者",
        help_text="【业务说明】患者真实姓名；【用法】前端展示及医生沟通；【示例】王女士；【参数】str；【返回值】str",
    )
    gender = models.PositiveSmallIntegerField(
        "性别",
        choices=choices.Gender.choices,
        default=choices.Gender.UNKNOWN,
        help_text="【业务说明】基础画像；【用法】表单选择；【示例】1=男；【参数】枚举；【返回值】int",
    )
    age = models.PositiveIntegerField(
        "年龄",
        null=True,
        blank=True,
        help_text="【业务说明】评估依从性风险；【用法】可空；【示例】55；【参数】int；【返回值】int",
    )
    id_card = models.CharField(
        "身份证号",
        max_length=18,
        blank=True,
        help_text="【业务说明】VIP 服务需要实名；【用法】销售录入；【示例】310************123；【参数】str；【返回值】str",
    )
    source = models.PositiveSmallIntegerField(
        "档案来源",
        choices=choices.PatientSource.choices,
        default=choices.PatientSource.SALES,
        help_text="【业务说明】区分线下/线上来源；【用法】统计渠道占比；【示例】1=线下；【参数】枚举；【返回值】int",
    )
    claim_status = models.PositiveSmallIntegerField(
        "认领状态",
        choices=choices.ClaimStatus.choices,
        default=choices.ClaimStatus.CLAIMED,
        help_text="【业务说明】标识档案是否有人管理；【用法】认领流程更新；【示例】0=待认领；【参数】枚举；【返回值】int",
    )
    service_status = models.PositiveSmallIntegerField(
        "服务等级",
        choices=choices.ServiceStatus.choices,
        default=choices.ServiceStatus.BASIC,
        help_text="【业务说明】冗余会员态；【用法】结合订单定时刷新；【示例】2=会员；【参数】枚举；【返回值】int",
    )
    sales = models.ForeignKey(
        "users.SalesProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="patients",
        verbose_name="归属销售",
        help_text="【业务说明】负责该患者的销售；【用法】销售建档绑定；【示例】SalesProfile#3；【参数】外键；【返回值】SalesProfile",
    )
    doctor = models.ForeignKey(
        "users.DoctorProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="patients",
        verbose_name="主治医生",
        help_text="【业务说明】主责医生；【用法】销售或运营指定；【示例】DoctorProfile#5；【参数】外键；【返回值】DoctorProfile",
    )
    membership_expire_at = models.DateTimeField(
        "会员到期时间",
        null=True,
        blank=True,
        help_text="【业务说明】会员到期时间；【用法】提醒续费；【示例】2025-05-01 00:00；【参数】datetime；【返回值】datetime",
    )
    last_active_at = models.DateTimeField(
        "最后活跃时间",
        null=True,
        blank=True,
        help_text="【业务说明】判断流失；【用法】ETL 更新；【示例】2025-01-10；【参数】datetime；【返回值】datetime",
    )
    device_sn = models.CharField(
        "设备 SN",
        max_length=50,
        blank=True,
        help_text="【业务说明】绑定硬件 SN；【用法】体征自动同步；【示例】POX-2024-8899；【参数】str；【返回值】str",
    )
    ec_name = models.CharField(
        "紧急联系人姓名",
        max_length=50,
        blank=True,
        help_text="【业务说明】紧急联系人姓名；【用法】高危预警联系；【示例】张先生；【参数】str；【返回值】str",
    )
    ec_phone = models.CharField(
        "紧急联系人电话",
        max_length=20,
        blank=True,
        help_text="【业务说明】紧急联系人电话；【用法】一键呼叫；【示例】13900000000；【参数】str；【返回值】str",
    )
    is_active = models.BooleanField(
        "是否有效",
        default=True,
        help_text="【业务说明】软删除/停用控制；【用法】注销档案时置 False；【示例】True；【参数】bool；【返回值】bool",
    )

    class Meta:
        verbose_name = "患者列表"
        verbose_name_plural = "患者列表"
        indexes = [
            models.Index(fields=["doctor"]),
            models.Index(fields=["phone"]),
        ]

    def clean(self):
        """
        【业务说明】限制 user 只能绑定 patient 类型账号，避免角色串联。
        【用法】`full_clean` 或 admin 保存时自动触发。
        【参数】self：当前实例。
        【返回值】None，若违规抛出 ValidationError。
        【使用示例】`profile.full_clean()`。
        """

        super().clean()
        if self.user and self.user.user_type != choices.UserType.PATIENT:
            raise ValidationError("患者档案仅能绑定患者/家属账号。")

    def __str__(self) -> str:
        """
        【业务说明】便于在日志/后台快速识别档案。
        【用法】`str(profile)`。
        【参数】self。
        【返回值】str，例如“王女士-13800138000”。
        【使用示例】Admin 列表展示。
        """

        return f"{self.name}-{self.phone}"
