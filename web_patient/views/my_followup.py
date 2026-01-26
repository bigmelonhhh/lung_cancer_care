import logging
from django.shortcuts import render
from django.http import HttpRequest, HttpResponse
from users.decorators import auto_wechat_login, check_patient, require_membership

logger = logging.getLogger(__name__)

@auto_wechat_login
@check_patient
@require_membership
def my_followup(request: HttpRequest) -> HttpResponse:
    """
    我的随访页面
    """
    # 模拟数据
    cycles = [
        {
            "name": "第三疗程 (当前疗程)",
            "tasks": [
                {
                    "id": 101,
                    "title": "随访问卷",
                    "date": "2025-12-21",
                    "status": "not_started",
                    "status_label": "未开始"
                },
                {
                    "id": 102,
                    "title": "随访问卷",
                    "date": "2025-12-14",
                    "status": "active",
                    "status_label": "去完成"
                },
                {
                    "id": 103,
                    "title": "随访问卷",
                    "date": "2025-12-06",
                    "status": "completed",
                    "status_label": "已完成"
                }
            ]
        },
        {
            "name": "第二疗程",
            "tasks": [
                {
                    "id": 201,
                    "title": "随访问卷",
                    "date": "2025-11-10",
                    "status": "incomplete",
                    "status_label": "未完成"
                },
                {
                    "id": 202,
                    "title": "随访问卷",
                    "date": "2025-11-01",
                    "status": "terminated",
                    "status_label": "已中止"
                }
            ]
        },
        {
            "name": "第一疗程",
            "tasks": [
                {
                    "id": 301,
                    "title": "随访问卷",
                    "date": "2025-10-09",
                    "status": "completed",
                    "status_label": "已完成"
                },
                {
                    "id": 302,
                    "title": "随访问卷",
                    "date": "2025-10-01",
                    "status": "completed",
                    "status_label": "已完成"
                }
            ]
        }
    ]

    context = {
        "cycles": cycles,
        "page_title": "我的随访"
    }

    return render(request, "web_patient/follow_up.html", context)
