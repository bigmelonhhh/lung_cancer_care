"""治疗计划相关模型。"""

from datetime import date

from django.db import models

from . import choices


class TreatmentCycle(models.Model):
    """疗程容器，绑定患者与周期信息。"""

    patient = models.ForeignKey(
        "users.PatientProfile",
        on_delete=models.CASCADE,
        related_name="treatment_cycles",
        verbose_name="患者",
    )
    name = models.CharField("疗程名称", max_length=50)
    start_date = models.DateField("开始日期")
    end_date = models.DateField("结束日期", null=True, blank=True)
    
    cycle_days = models.PositiveIntegerField("周期天数", default=21)
    status = models.PositiveSmallIntegerField(
        "状态",
        choices=choices.TreatmentCycleStatus.choices,
        default=choices.TreatmentCycleStatus.IN_PROGRESS,
    )

    class Meta:
        db_table = "core_treatment_cycles"
        verbose_name = "治疗疗程"
        verbose_name_plural = "治疗疗程"
        ordering = ("-start_date",)

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.patient.name}-{self.name}"

    @property
    def is_finished(self) -> bool:
        """
        【业务说明】综合计划结束日期与状态判断该疗程是否已结束。
        【规则】
        - 若状态为“已结束”或“已终止”，视为已结束；
        - 否则若当前日期晚于计划结束日期（自然结束），视为已结束；
        - 其它情况视为未结束。
        """

        today = date.today()
        if self.status in (
            choices.TreatmentCycleStatus.COMPLETED,
            choices.TreatmentCycleStatus.TERMINATED,
        ):
            return True
        if self.end_date and today > self.end_date:
            return True
        return False

    def refresh_status_if_expired(self) -> bool:
        """
        【业务说明】在读取状态前刷新疗程状态，避免过期仍显示进行中。
        【规则】
        - 若状态不是“进行中”，直接返回 False；
        - 若状态为“进行中”且已超过结束日期，自动更新为“已结束”，返回 False；
        - 若状态为“进行中”且未过期，返回 True。
        """

        if self.status != choices.TreatmentCycleStatus.IN_PROGRESS:
            return False
        if self.end_date and date.today() > self.end_date:
            self.status = choices.TreatmentCycleStatus.COMPLETED
            self.save(update_fields=["status"])
            return False
        return True
