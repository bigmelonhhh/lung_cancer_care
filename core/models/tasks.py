"""每日任务实例模型。"""

from django.db import models

from . import choices


class DailyTask(models.Model):
    """每日待办任务，由计划/监测调度生成。"""

    patient = models.ForeignKey(
        "users.PatientProfile",
        on_delete=models.CASCADE,
        related_name="daily_tasks",
        verbose_name="患者",
    )
    plan_item = models.ForeignKey(
        "core.PlanItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="daily_tasks",
        verbose_name="来源计划",
    )
    task_date = models.DateField("任务日期")
    task_type = models.PositiveSmallIntegerField(
        "任务类型",
        choices=choices.PlanItemCategory.choices,
    )
    title = models.CharField("任务标题", max_length=100)
    detail = models.TextField("任务描述", blank=True)
    status = models.PositiveSmallIntegerField(
        "完成状态",
        choices=choices.TaskStatus.choices,
        default=choices.TaskStatus.PENDING,
    )
    completed_at = models.DateTimeField("完成时间", null=True, blank=True)
    is_locked = models.BooleanField("是否锁定", default=False)
    related_report_type = models.PositiveSmallIntegerField(
        "关联报告类型",
        choices=choices.ReportType.choices,
        null=True,
        blank=True,
    )
    interaction_payload = models.JSONField(
        "交互配置快照",
        blank=True,
        default=dict,
        help_text="生成任务时从 plan_item.interaction_config 拷贝的快照。",
    )

    class Meta:
        db_table = "core_daily_tasks"
        verbose_name = "每日任务"
        verbose_name_plural = "每日任务"
        indexes = [
            models.Index(fields=["patient", "task_date"], name="idx_core_task_patient_date"),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.task_date} - {self.title}"
