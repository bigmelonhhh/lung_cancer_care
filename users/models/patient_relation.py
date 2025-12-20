from django.core.exceptions import ValidationError
from django.db import models

from users import choices
from users.models.base import TimeStampedModel


class PatientRelation(TimeStampedModel):
    """
    【业务说明】描述患者与家属/代理账号之间的权限关系。
    【用法】扫码认领、自注册、权限调整都会创建/更新记录。
    【使用示例】`PatientRelation.objects.create(patient=profile, user=user, relation_type=RelationType.CHILD)`。
    【参数】包含患者与账号的外键、权限字段。
    【返回值】Model 实例。
    """

    patient = models.ForeignKey(
        "users.PatientProfile",
        on_delete=models.CASCADE,
        related_name="relations",
        verbose_name="患者档案",
        help_text="【业务说明】被管理的患者档案；【用法】必填；【示例】PatientProfile#5；【参数】外键；【返回值】PatientProfile",
    )
    user = models.ForeignKey(
        "users.CustomUser",
        on_delete=models.CASCADE,
        related_name="patient_relations",
        verbose_name="授权账号",
        help_text="【业务说明】拥有访问权限的账号；【用法】绑定家属；【示例】CustomUser#10；【参数】外键；【返回值】CustomUser",
    )
    relation_type = models.PositiveSmallIntegerField(
        "关系类型",
        choices=choices.RelationType.choices,
        default=choices.RelationType.SELF,
        help_text="【业务说明】关系类型；【用法】用于展示与权限策略；【示例】3=子女；【参数】枚举；【返回值】int",
    )
    relation_name = models.CharField(
        "关系备注",
        max_length=20,
        blank=True,
        help_text="【业务说明】自定义关系说明；【用法】前端展示例如“女儿”；【示例】女儿；【参数】str；【返回值】str",
    )
    name = models.CharField(
        "家属姓名",
        max_length=50,
        blank=True,
        help_text="【业务说明】家属的真实姓名；【用法】可选填写；【示例】张三；【参数】str；【返回值】str",
    )
    phone = models.CharField(
        "手机号",
        max_length=15,
        blank=True,
        null=True,
        help_text="【业务说明】家属的手机号；【用法】可选填写；【示例】13800138000；【参数】str；【返回值】str",
    )
    
    receive_alert_msg = models.BooleanField(
        "是否接收通知",
        default=False,
        help_text="【业务说明】是否接收模板消息；【用法】用户自行勾选；【示例】False；【参数】bool；【返回值】bool",
    )
    is_active = models.BooleanField(
        "是否有效",
        default=True,
        help_text="【业务说明】软删除标记；【用法】解绑时置为 False；【示例】True；【参数】bool；【返回值】bool",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["patient", "user"], name="uq_patient_user_relation"),
        ]
        verbose_name = "Patient Relation"
        verbose_name_plural = "Patient Relations"

    def clean(self):
        """
        【业务说明】确保只有患者/家属账号能被添加为亲情关系。
        【用法】`full_clean` 时自动调用。
        【参数】self。
        【返回值】None，违规抛错。
        【使用示例】`relation.full_clean()`。
        """

        super().clean()
        if self.user.user_type != choices.UserType.PATIENT:
            raise ValidationError("只有患者/家属账号才能建立代理关系。")

    def __str__(self) -> str:
        """
        【业务说明】方便调试输出。
        【用法】`str(relation)`。
        【参数】self。
        【返回值】str，例如“5->10”。
        【使用示例】日志打印。
        """

        return f"{self.patient_id}->{self.user_id}"
