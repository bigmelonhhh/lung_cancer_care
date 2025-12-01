from django.db import models

from users.models.base import TimeStampedModel


class SystemDocument(TimeStampedModel):
    """
    【业务说明】系统级文案/协议，例如：关于我们、用户协议、隐私政策、知情同意书等。
    【用法】在后台以 Markdown 文本录入，前台渲染为 HTML。
    """

    key = models.CharField(
        "唯一标识 Key",
        max_length=50,
        unique=True,
        help_text='【说明】程序调用用的标识，如 "about_us"、"user_agreement"、"privacy_policy"、"informed_consent"；创建后请勿随意修改。',
    )
    title = models.CharField(
        "标题",
        max_length=100,
        help_text="【说明】文案标题，例如“用户协议”。",
    )
    content = models.TextField(
        "正文内容（Markdown）",
        help_text="【说明】支持 Markdown 语法，自动渲染为 HTML；可使用标题、列表、加粗等格式。",
    )
    version = models.CharField(
        "版本号",
        max_length=20,
        blank=True,
        help_text='【说明】可选版本号，例如 "1.0"、"2025.01"。',
    )
    is_active = models.BooleanField(
        "是否启用",
        default=True,
        help_text="【说明】控制该文案是否对前端可见。",
    )

    class Meta:
        verbose_name = "系统文案/协议"
        verbose_name_plural = "系统文案/协议"
        ordering = ("-updated_at",)

    def __str__(self) -> str:
        return f"{self.title} ({self.key})"

