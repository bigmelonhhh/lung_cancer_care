"""核心业务模型通用枚举。"""

from django.db import models


class ReportType(models.IntegerChoices):
    """复查报告类型，供检查库和任务引用。"""

    UNKNOWN = 0, "未分类"
    CHEST_CT = 1, "胸部CT"
    BLOOD_ROUTINE = 2, "血常规"
    BIOCHEMISTRY = 3, "生化检查"
    TUMOR_MARKER = 4, "肿瘤标志物"
    ECG = 5, "心电图"


class TreatmentCycleStatus(models.IntegerChoices):
    IN_PROGRESS = 1, "进行中"
    COMPLETED = 2, "已结束"
    TERMINATED = 3, "已终止"


class PlanItemCategory(models.IntegerChoices):
    MEDICATION = 1, "用药"
    CHECKUP = 2, "检查"
    QUESTIONNAIRE = 3, "问卷"
    MONITORING = 4, "监测"




class PlanItemStatus(models.IntegerChoices):
    ACTIVE = 1, "生效"
    DISABLED = 0, "停用"


class PriorityLevel(models.TextChoices):
    FIRST_LINE = "1st_line", "一线"
    SECOND_LINE = "2nd_line", "二线"
    MAINTENANCE = "maintenance", "维持"


class CheckupCategory(models.IntegerChoices):
    IMAGING = 1, "影像"
    BLOOD = 2, "血液"
    FUNCTION = 3, "功能"


class TaskStatus(models.IntegerChoices):
    PENDING = 0, "未做"
    COMPLETED = 1, "已完成"
    IGNORED = 2, "已忽略"


class QuestionType(models.TextChoices):
    SINGLE = "SINGLE", "单选题"
    MULTIPLE = "MULTIPLE", "多选题"
    TEXT = "TEXT", "问答/填空"
