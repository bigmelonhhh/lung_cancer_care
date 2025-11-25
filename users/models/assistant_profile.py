from django.core.exceptions import ValidationError
from django.db import models

from users import choices
from users.models.base import TimeStampedModel


class AssistantProfile(TimeStampedModel):
    """
    【业务说明】维护医生助理的人事与绑定关系，支撑工作室协同。
    【用法】助理入职后创建档案，并通过多对多关系绑定医生。
    【使用示例】`AssistantProfile.objects.create(user=user, name="张助理")`。
    【参数】字段详见定义。
    【返回值】Model。
    """

    user = models.OneToOneField(
        "users.CustomUser",
        on_delete=models.CASCADE,
        related_name="assistant_profile",
        verbose_name="助理账号",
        help_text="【业务说明】助理账号；【用法】user_type=助理；【示例】CustomUser#40；【参数】外键；【返回值】CustomUser",
    )
    name = models.CharField(
        "助理姓名",
        max_length=50,
        help_text="【业务说明】助理姓名；【用法】聊天等处展示；【示例】张助理；【参数】str；【返回值】str",
    )
    status = models.PositiveSmallIntegerField(
        "助理状态",
        choices=choices.AssistantStatus.choices,
        default=choices.AssistantStatus.ACTIVE,
        help_text="【业务说明】在职/离职标记；【用法】控制是否可接收任务；【示例】1=在职；【参数】枚举；【返回值】int",
    )
    work_phone = models.CharField(
        "工作电话",
        max_length=20,
        blank=True,
        help_text="【业务说明】工作联系电话；【用法】医生可快速拨号；【示例】021-88888888；【参数】str；【返回值】str",
    )
    joined_at = models.DateField(
        "入职日期",
        null=True,
        blank=True,
        help_text="【业务说明】入职日期；【用法】人事统计；【示例】2024-09-01；【参数】date；【返回值】date",
    )
    doctors = models.ManyToManyField(
        "users.DoctorProfile",
        through="users.DoctorAssistantMap",
        related_name="assistants",
        blank=True,
        verbose_name="负责医生",
        help_text="【业务说明】助理支持的医生列表；【用法】通过 doctor_assistant_map 维护；【示例】多对多；【参数】M2M；【返回值】QuerySet",
    )

    class Meta:
        verbose_name = "医生助理"
        verbose_name_plural = "医生助理"

    def clean(self):
        """
        【业务说明】限制只能绑定助理账号。
        【用法】保存前校验。
        【参数】self。
        【返回值】None。
        【使用示例】`profile.full_clean()`。
        """

        super().clean()
        if not self.user_id:
            return
        if self.user.user_type != choices.UserType.ASSISTANT:
            raise ValidationError("关联账号必须是助理类型。")

    def __str__(self) -> str:
        """
        【业务说明】输出助理名称及状态。
        【用法】`str(profile)`。
        【参数】self。
        【返回值】str，例如“张助理(在职)”。
        【使用示例】后台列表。
        """

        return f"{self.name}({self.get_status_display()})"
