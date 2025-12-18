"""Monitoring template related services."""

from __future__ import annotations

from typing import List

from core.models import MonitoringTemplate


class MonitoringService:
    """Monitoring template service (类似 QuestionnaireService)。"""

    @staticmethod
    def get_active_templates() -> List[MonitoringTemplate]:
        """
        【功能说明】
        - 查询所有启用中的一般监测模板（is_active=True）；
        - 按 sort_order、name 排序；
        - 主要用于医生端“计划设置”等场景构建监测项目列表。

        【返回参数说明】
        - 返回 List[MonitoringTemplate]。
        """
        return list(
            MonitoringTemplate.objects.filter(is_active=True).order_by("sort_order", "name")
        )
