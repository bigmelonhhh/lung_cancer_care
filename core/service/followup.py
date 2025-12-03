"""随访问卷计划库相关业务服务。"""

from __future__ import annotations

from typing import Iterable, List, TypedDict

from core.models import FollowupLibrary


class FollowupPlanItem(TypedDict):
    """用于前端展示的随访计划条目结构。"""

    lib_id: int
    name: str
    schedule: list[int]


def get_active_followup_library() -> List[FollowupPlanItem]:
    """
    【功能说明】
    - 查询所有启用中的随访模板（is_active=True），按 sort_order、name 排序；
    - 转换为前端展示用的结构。

    【返回参数说明】
    - 返回 FollowupPlanItem 列表：
      - lib_id: 随访库主键 ID；
      - name: 随访名称；
      - schedule: 推荐执行天数模板。
    """

    qs: Iterable[FollowupLibrary] = FollowupLibrary.objects.filter(is_active=True)

    items: List[FollowupPlanItem] = []
    for follow in qs:
        items.append(
            FollowupPlanItem(
                lib_id=follow.id,
                name=follow.name,
                schedule=list(follow.schedule_days_template or []),
            )
        )
    return items

