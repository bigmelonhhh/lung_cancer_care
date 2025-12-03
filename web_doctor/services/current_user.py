"""
医生端工作台相关的展示辅助逻辑。
"""

from users.models import CustomUser

def get_user_display_name(user: CustomUser) -> str:
    """
    生成医生工作台顶部使用的展示名称：
    - 优先展示医生姓名
    - 医生不存在时展示助理姓名
    - 双方都没有时降级为账号相关字段（昵称/姓名/用户名/手机号）
    """
    if not user or not getattr(user, "is_authenticated", False):
        return ""

    doctor_profile = getattr(user, "doctor_profile", None)
    assistant_profile = getattr(user, "assistant_profile", None)

    if doctor_profile and getattr(doctor_profile, "name", ""):
        return doctor_profile.name
    if assistant_profile and getattr(assistant_profile, "name", ""):
        return assistant_profile.name

    # 兜底策略：优先昵称，其次姓名/全名，最后用户名或手机号
    if getattr(user, "wx_nickname", ""):
        return user.wx_nickname
    if getattr(user, "name", ""):
        return user.name
    if hasattr(user, "get_full_name") and user.get_full_name():
        return user.get_full_name()

    return getattr(user, "username", "") or getattr(user, "phone", "")

