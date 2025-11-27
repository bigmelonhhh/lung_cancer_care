from django.core.exceptions import ValidationError
from django.db import models

from users import choices
from users.models.base import TimeStampedModel


class DoctorProfile(TimeStampedModel):
    """
    【业务说明】记录医生的执业信息、所属工作室及冗余数据，支撑工作室与患者管理。
    【用法】销售拓展医生后创建档案，供工作室展示与分配患者。
    【使用示例】`DoctorProfile.objects.create(user=user, name="张主任", hospital="市一医院")`。
    【参数】字段详见下文。
    【返回值】Model 实例。
    """

    user = models.OneToOneField(
        "users.CustomUser",
        on_delete=models.CASCADE,
        related_name="doctor_profile",
        verbose_name="医生账号",
        help_text="【业务说明】医生登录账号；【用法】user_type=医生；【示例】CustomUser#30；【参数】外键；【返回值】CustomUser",
    )
    name = models.CharField(
        "* 医生姓名",
        max_length=50,
        help_text="【业务说明】医生姓名；【用法】前端展示；【示例】张主任；【参数】str；【返回值】str",
    )
    hospital = models.CharField(
        "* 所属医院",
        max_length=100,
        help_text="【业务说明】所属医院；【用法】展示/筛选；【示例】上海市第一人民医院；【参数】str；【返回值】str",
    )
    department = models.CharField(
        "* 所属科室",
        max_length=50,
        help_text="【业务说明】所属科室；【用法】帮助患者识别；【示例】肿瘤科；【参数】str；【返回值】str",
    )
    title = models.CharField(
        "职称",
        max_length=50,
        blank=True,
        help_text="【业务说明】职称；【用法】宣传素材；【示例】主任医师；【参数】str；【返回值】str",
    )
    studio = models.ForeignKey(
        "users.DoctorStudio",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="doctors",
        verbose_name="所属工作室",
        help_text="【业务说明】该医生所属工作室；【用法】展示二维码等；【示例】Studio#1；【参数】外键；【返回值】DoctorStudio",
    )
    sales = models.ManyToManyField(
        "users.SalesProfile",
        related_name="doctors",
        blank=True,
        verbose_name="负责销售团队",
        help_text="【业务说明】负责维护该医生的销售团队；【用法】绩效归属；【示例】SalesProfile#2；【参数】多选；【返回值】SalesProfile",
    )
    managed_patient_count = models.PositiveIntegerField(
        "在管患者数",
        default=0,
        help_text="【业务说明】统计指标：当前在管患者量；【用法】大屏展示；【示例】88；【参数】int；【返回值】int",
    )

    class Meta:
        verbose_name = "医生档案"
        verbose_name_plural = "医生档案"

    def clean(self):
        """
        【业务说明】防止非医生账号误绑定。
        【用法】保存前校验。
        【参数】self。
        【返回值】None。
        【使用示例】`profile.full_clean()`。
        """

        super().clean()
        if not self.user_id:
            return
        if self.user.user_type != choices.UserType.DOCTOR:
            raise ValidationError("关联账号必须是医生类型。")

    def __str__(self) -> str:
        """
        【业务说明】后台展示医生信息。
        【用法】`str(profile)`。
        【参数】self。
        【返回值】str，如“张主任-市一医院”。
        【使用示例】日志记录。
        """

        return f"{self.name}-{self.hospital}"
