"""复查项目标准库相关业务服务。"""

from __future__ import annotations

from typing import Iterable, List, TypedDict

from core.models import CheckupLibrary


class CheckupPlanItem(TypedDict):
    """用于前端展示的复查计划条目结构。"""

    lib_id: int
    name: str
    category: str
    is_active: bool
    schedule: list[int]


def get_active_checkup_library() -> List[CheckupPlanItem]:
    """
    【功能说明】
    - 查询所有启用中的复查项目（is_active=True），按 sort_order、name 排序；
    - 转换为前端展示友好的结构，用于“医院计划设置”中的复查计划区域。

    【返回参数说明】
    - 返回 CheckupPlanItem 列表：
      - lib_id: 复查库主键 ID；
      - name: 检查项目名称；
      - category: 分类展示文本；
      - schedule: 推荐执行天数模板。
    """

    qs: Iterable[CheckupLibrary] = CheckupLibrary.objects.filter(is_active=True)

    items: List[CheckupPlanItem] = []
    for item in qs:
        items.append(
            CheckupPlanItem(
                lib_id=item.id,
                name=item.name,
                category=item.get_category_display(),
                is_active=item.is_active,
                schedule=list(item.schedule_days_template or []),
            )
        )
    return items
