from django.db import models


class UserType(models.IntegerChoices):
    """【业务说明】区分不同账号角色；【用法】CustomUser.user_type；【使用示例】UserType.DOCTOR。"""

    PATIENT = 1, "患者/家属"
    DOCTOR = 2, "主治医生"
    SALES = 3, "销售专员"
    ADMIN = 4, "平台管理员"
    ASSISTANT = 5, "医生助理"


class Gender(models.IntegerChoices):
    """【业务说明】患者性别枚举；【用法】PatientProfile.gender。"""

    UNKNOWN = 0, "未知"
    MALE = 1, "男"
    FEMALE = 2, "女"


class PatientSource(models.IntegerChoices):
    """【业务说明】档案来源渠道；【用法】source 字段。"""

    SALES = 1, "线下销售建档"
    SELF = 2, "线上自注册"


class ClaimStatus(models.IntegerChoices):
    """【业务说明】认领状态；【用法】claim_status。"""

    PENDING = 0, "待认领"
    CLAIMED = 1, "已认领"


class RelationType(models.IntegerChoices):
    """【业务说明】亲情/代理关系类型；【用法】relation_type。"""

    SELF = 1, "本人"
    PARENT = 2, "父母"
    CHILD = 3, "子女"
    SPOUSE = 4, "配偶"
    OTHER = 5, "其它"


class AssistantStatus(models.IntegerChoices):
    """【业务说明】助理在职状态；【用法】AssistantProfile.status。"""

    ACTIVE = 1, "在职"
    INACTIVE = 2, "离职"
