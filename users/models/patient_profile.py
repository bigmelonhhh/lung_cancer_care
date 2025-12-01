from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

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
    birth_date = models.DateField(
        "出生日期",
        null=True,
        blank=True,
        help_text="【业务说明】用于推算年龄、评估依从风险；【用法】可空；【示例】1969-05-10；【参数】date；【返回值】date",
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
    address = models.CharField(
        "联系地址",
        max_length=100,
        blank=True,
        help_text="【业务说明】患者联系地址；【用法】邮寄资料或上门；【示例】上海市浦东新区XX路；【参数】str；【返回值】str",
    )
    ec_relation = models.CharField(
        "紧急联系人关系",
        max_length=20,
        blank=True,
        help_text="【业务说明】如父子/配偶；【用法】便于识别联系人；【示例】父子；【参数】str；【返回值】str",
    )
    qrcode_url = models.URLField(
        "绑定二维码",
        blank=True,
        help_text="【业务说明】缓存患者绑定二维码 URL；【用法】销售端展示扫码绑定；【示例】https://wx.qq.com/qrcode；【参数】str；【返回值】str",
    )
    qrcode_expire_at = models.DateTimeField(
        "二维码过期时间",
        null=True,
        blank=True,
        help_text="【业务说明】记录二维码失效时间，避免频繁请求微信；【用法】每次生成更新；【示例】2025-01-01 10:00；【参数】datetime；【返回值】datetime",
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

    @property
    def age(self):
        """
        【业务说明】按出生日期计算年龄，便于兼容旧逻辑。
        """

        if not self.birth_date:
            return None
        today = date.today()
        return today.year - self.birth_date.year - (
            (today.month, today.day) < (self.birth_date.month, self.birth_date.day)
        )

    @property
    def masked_name(self) -> str:
        """
        【业务说明】脱敏展示姓名。
        【规则】
        - 1 个字：显示原名。
        - 2 个字：显示首字 + *。
        - ≥3 个字：显示首尾，中间以 * 填充。
        """

        if not self.name:
            return ""
        name = self.name.strip()
        length = len(name)
        if length <= 1:
            return name
        if length == 2:
            return f"{name[0]}*"
        return f"{name[0]}{'*' * (length - 2)}{name[-1]}"

    def _compute_membership_state(self) -> str:
        """
        返回会员状态：
        - active：存在未过期的付费订单
        - expired：曾付费但已过期
        - none：从未付费
        """

        from market.models import Order

        today = timezone.localdate()
        paid_orders = (
            Order.objects.select_related("product")
            .filter(patient=self, status=Order.Status.PAID, paid_at__isnull=False)
            .order_by("-paid_at")
        )

        had_paid = False
        for order in paid_orders:
            had_paid = True
            duration = order.product.duration_days or 0
            if duration <= 0:
                continue
            start_date = timezone.localtime(order.paid_at).date()
            end_date = start_date + timedelta(days=duration - 1)
            if today <= end_date:
                return "active"

        if had_paid:
            return "expired"
        return "none"

    def has_active_membership(self) -> bool:
        """是否拥有有效会员服务。"""

        return self._compute_membership_state() == "active"

    def get_service_status_display(self) -> str:
        """兼容旧模板调用，返回当前会员状态文案。"""

        state = self._compute_membership_state()
        if state == "active":
            return "付费会员"
        if state == "expired":
            return "已过期"
        return "免费会员"
