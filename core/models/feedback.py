from django.db import models


class Feedback(models.Model):
    class Type(models.IntegerChoices):
        ISSUE = 1, "反馈问题"
        SUGGESTION = 2, "提出建议"

    class Status(models.IntegerChoices):
        PENDING = 1, "待处理"
        PROCESSING = 2, "处理中"
        RESOLVED = 3, "已解决"

    user = models.ForeignKey(
        "users.PatientProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="feedbacks",
        verbose_name="患者",
    )
    feedback_type = models.PositiveSmallIntegerField(
        "反馈类型",
        choices=Type.choices,
        default=Type.ISSUE,
    )
    content = models.TextField("反馈内容", max_length=500)
    contact_phone = models.CharField("联系方式", max_length=20, blank=True)
    status = models.PositiveSmallIntegerField(
        "处理状态",
        choices=Status.choices,
        default=Status.PENDING,
    )
    created_at = models.DateTimeField("提交时间", auto_now_add=True)

    class Meta:
        verbose_name = "意见反馈"
        verbose_name_plural = "意见反馈"
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.get_feedback_type_display()} - {self.created_at:%Y-%m-%d}"


class FeedbackImage(models.Model):
    feedback = models.ForeignKey(
        Feedback,
        on_delete=models.CASCADE,
        related_name="images",
        verbose_name="反馈",
    )
    image = models.ImageField("图片", upload_to="feedback/%Y/%m/")

    class Meta:
        verbose_name = "反馈图片"
        verbose_name_plural = "反馈图片"

    def __str__(self):
        return f"图片 - {self.feedback_id}"
