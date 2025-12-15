"""每日任务实例模型。"""

from django.db import models

from . import choices


class DailyTaskQuerySet(models.QuerySet):
    """每日任务查询集封装，提供常用过滤方法。"""

    def for_date(self, task_date):
        """按任务日期过滤。"""
        return self.filter(task_date=task_date)

    def for_patient(self, patient):
        """按患者过滤。"""
        return self.filter(patient=patient)

    def pending(self):
        """筛选待完成任务。"""
        return self.filter(status=choices.TaskStatus.PENDING)

    def completed(self):
        """筛选已完成任务。"""
        return self.filter(status=choices.TaskStatus.COMPLETED)


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

    # 自定义查询集
    objects = DailyTaskQuerySet.as_manager()

    class Meta:
        db_table = "core_daily_tasks"
        verbose_name = "每日任务"
        verbose_name_plural = "每日任务"
        indexes = [
            models.Index(fields=["patient", "task_date"], name="idx_core_task_patient_date"),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.task_date} - {self.title}"

    # 业务辅助方法
    @property
    def is_completed(self) -> bool:
        """是否已完成。"""
        return self.status == choices.TaskStatus.COMPLETED

    def mark_completed(self, when=None, save=True):
        """标记任务为已完成。

        Args:
            when: 完成时间，默认使用当前时间（由数据库/上层逻辑决定）。
            save: 是否立即保存到数据库。
        """
        # 为避免直接依赖 timezone，这里将具体完成时间的赋值策略交由上层调用控制。
        self.status = choices.TaskStatus.COMPLETED
        if when is not None:
            self.completed_at = when
        if save:
            self.save(update_fields=["status", "completed_at"])
