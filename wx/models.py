from django.db import models
from users.models.base import TimeStampedModel

class MessageTemplate(TimeStampedModel):
    """
    【业务说明】用于存放系统发送给用户的各类文案，支持动态变量。
    【用法】通过 code 查找模板，使用 format 渲染变量。
    【使用示例】`MessageTemplate.objects.create(code="welcome", content="你好，{name}")`。
    """
    
    code = models.CharField(
        "模版编码",
        max_length=50,
        unique=True,
        db_index=True,
        help_text="【程序员看】唯一标识，代码中通过此字段获取文案。例如：bind_success_self"
    )
    title = models.CharField(
        "模版名称",
        max_length=100,
        help_text="【运营看】描述这个文案是用在哪里的。"
    )
    content = models.TextField(
        "文案内容",
        help_text="支持变量替换。例如：你好，{name}。请确保变量名与开发约定一致。"
    )
    available_vars = models.CharField(
        "可用变量说明",
        max_length=255,
        blank=True,
        help_text="备注提示，例如：{name}=患者姓名, {doctor}=医生姓名"
    )
    is_active = models.BooleanField("是否启用", default=True)

    class Meta:
        verbose_name = "微信消息文案库"
        verbose_name_plural = "微信消息文案库"

    def __str__(self):
        return f"{self.title} ({self.code})"