"""
【业务说明】提供用户域的视图权限装饰器，防止不同角色串台操作。
【用法】在类视图的 `dispatch` 或函数视图上添加装饰器，例如 `@check_doctor`。
【规范】实现依赖 Django 官方的 `user_passes_test`，未登录跳转登录页，权限不足抛 403。
"""

from typing import Callable, Iterable

from django.conf import settings
from django.contrib.auth.decorators import user_passes_test
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse

from users import choices

RoleCheck = Callable[[HttpRequest], bool]
ViewFunc = Callable[[HttpRequest], HttpResponse]


LOGIN_URL = getattr(settings, "LOGIN_URL", "login")
"""登录地址，供未认证用户重定向使用。"""


def _user_role_guard(user, allowed_roles: Iterable[int]) -> bool:
    """
    【业务说明】统一封装权限判断，满足“未登录 -> False；已登录但角色不符 -> PermissionDenied；通过 -> True”。
    【用法】作为 `user_passes_test` 的 test_func。
    【参数】user：当前 request.user；allowed_roles：允许访问的 user_type 列表。
    【返回值】bool，仅在通过校验时返回 True。
    """

    if not getattr(user, "is_authenticated", False):
        return False

    if not getattr(user, "is_active", False):
        raise PermissionDenied("账号已停用")

    if getattr(user, "user_type", None) not in allowed_roles:
        raise PermissionDenied("无权访问该资源")

    return True


def _build_role_decorator(*roles: int) -> Callable[[ViewFunc], ViewFunc]:
    """
    【业务说明】动态生成角色校验装饰器，便于扩展多角色共用策略。
    【用法】内部被 `check_patient`、`check_doctor_or_assistant` 等方法调用。
    【参数】roles: 允许访问的 user_type 枚举。
    【返回值】可直接作用于视图函数/方法的装饰器。
    【示例】`@_build_role_decorator(choices.UserType.DOCTOR)`。
    """

    def decorator(view_func: ViewFunc) -> ViewFunc:
        return user_passes_test(
            lambda user: _user_role_guard(user, roles),
            login_url=LOGIN_URL,
            raise_exception=True,
        )(view_func)

    return decorator


def check_patient(view_func: ViewFunc) -> ViewFunc:
    """
    【业务说明】限制仅患者/家属访问。
    【用法】`@check_patient`。
    【参数】view_func：目标视图。
    【返回值】包装后的视图。
    【示例】患者个人中心。
    """

    return _build_role_decorator(choices.UserType.PATIENT)(view_func)


def check_doctor(view_func: ViewFunc) -> ViewFunc:
    """医生专属装饰器。"""

    return _build_role_decorator(choices.UserType.DOCTOR)(view_func)


def check_sales(view_func: ViewFunc) -> ViewFunc:
    """销售专属装饰器。"""

    return _build_role_decorator(choices.UserType.SALES)(view_func)


def check_admin(view_func: ViewFunc) -> ViewFunc:
    """管理员专属装饰器。"""

    return _build_role_decorator(choices.UserType.ADMIN)(view_func)


def check_assistant(view_func: ViewFunc) -> ViewFunc:
    """医生助理专属装饰器。"""

    return _build_role_decorator(choices.UserType.ASSISTANT)(view_func)


def check_doctor_or_assistant(view_func: ViewFunc) -> ViewFunc:
    """
    【业务说明】医生与助理可同时访问，例如工作室运营面板。
    【用法】`@check_doctor_or_assistant`。
    【参数】view_func：目标视图。
    【返回值】包装后的视图。
    """
    return _build_role_decorator(choices.UserType.DOCTOR, choices.UserType.ASSISTANT)(view_func)

def check_doctor_or_assistant_or_sales(view_func: ViewFunc) -> ViewFunc:
    """
    【业务说明】医生与助理可同时访问，例如工作室运营面板。
    【用法】`@check_doctor_or_assistant`。
    【参数】view_func：目标视图。
    【返回值】包装后的视图。
    """

    return _build_role_decorator(choices.UserType.DOCTOR, choices.UserType.ASSISTANT, choices.UserType.SALES)(view_func)


__all__ = [
    "check_patient",
    "check_doctor",
    "check_sales",
    "check_admin",
    "check_assistant",
    "check_doctor_or_assistant",
]
