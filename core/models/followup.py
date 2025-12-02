"""随访问卷计划库。"""

from django.db import models


class FollowupLibrary(models.Model):
    """随访计划模板，供疗程计划引用。"""

    name = models.CharField("随访名称", max_length=50)
    code = models.CharField(
        "随访编码",
        max_length=50,
        unique=True,
        help_text="唯一英文编码，例如 FOLLOW_PAIN、FOLLOW_SLEEP。",
    )
    schedule_days_template = models.JSONField(
        "推荐执行天(周期内)",
        default=list,
        blank=True,
        help_text="周期内执行的 DayIndex 集合，例如 [7, 14, 21]。",
    )
    is_active = models.BooleanField("是否启用", default=True)
    sort_order = models.PositiveIntegerField("排序权重", default=0)

    FOLLOWUP_DETAILS={"HX":"呼吸",
                      "TT":"疼痛",
                      "SY":"食欲",
                      "KS":"咳嗽/痰色",
                      "TN":"体能",
                      "SM":"睡眠",
                      "XL":"心理/情绪"}

    class Meta:
        db_table = "core_followup_library"
        verbose_name = "随访项目"
        verbose_name_plural = "随访项目"
        ordering = ("sort_order", "name")

    def __str__(self) -> str:  # pragma: no cover
        return self.name

