from django.db import models

from users.models.base import TimeStampedModel


class DoctorStudio(TimeStampedModel):
    """
    【业务说明】医生专家工作室实体，包含名称、二维码及负责人。
    【用法】医生创建工作室后，用于患者扫码入组、展示品牌。
    【使用示例】`DoctorStudio.objects.create(name="张主任工作室", code="STU001", owner_doctor=doctor)`。
    【参数】字段定义如下。
    【返回值】Model。
    """

    name = models.CharField(
        "工作室名称",
        max_length=50,
        help_text="【业务说明】工作室对外名称；【用法】展示；【示例】张主任慢病工作室；【参数】str；【返回值】str",
    )
    code = models.CharField(
        "工作室编码",
        max_length=20,
        unique=True,
        help_text="【业务说明】内部唯一编码，用于生成二维码；【用法】不可重复；【示例】STU001；【参数】str；【返回值】str",
    )
    
    intro = models.TextField(
        "工作室介绍",
        blank=True,
        help_text="【业务说明】工作室简介；【用法】介绍服务内容；【示例】专注慢病精准康复；【参数】text；【返回值】str",
    )
    owner_doctor = models.ForeignKey(
        "users.DoctorProfile",
        on_delete=models.CASCADE,
        related_name="owned_studios",
        verbose_name="负责人",
        help_text="【业务说明】工作室负责人；【用法】必须指定；【示例】DoctorProfile#1；【参数】外键；【返回值】DoctorProfile",
    )

    class Meta:
        verbose_name = "医生工作室"
        verbose_name_plural = "医生工作室"

    def __str__(self) -> str:
        """
        【业务说明】返回工作室名称，便于展示。
        【用法】`str(studio)`。
        【参数】self。
        【返回值】str。
        【使用示例】后台列表。
        """

        return self.name
