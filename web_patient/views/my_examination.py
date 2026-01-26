import logging

from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from users.decorators import auto_wechat_login, check_patient, require_membership
from core.models import DailyTask
from health_data.models.test_report import TestReport

logger = logging.getLogger(__name__)


@auto_wechat_login
@check_patient
@require_membership
def my_examination(request: HttpRequest) -> HttpResponse:
    """
    我的复查页面
    """
    cycles = [
        {
            "name": "第三疗程 (当前疗程)",
            "tasks": [
                {
                    "id": 101,
                    "title": "复查项目",
                    "date": "2025-12-21",
                    "status": "not_started",
                    "status_label": "未开始",
                },
                {
                    "id": 102,
                    "title": "复查项目",
                    "date": "2025-12-14",
                    "status": "active",
                    "status_label": "去完成",
                },
                {
                    "id": 103,
                    "title": "复查项目",
                    "date": "2025-12-06",
                    "status": "completed",
                    "status_label": "已完成",
                },
            ],
        },
        {
            "name": "第二疗程",
            "tasks": [
                {
                    "id": 201,
                    "title": "复查项目",
                    "date": "2025-11-10",
                    "status": "incomplete",
                    "status_label": "未完成",
                },
                {
                    "id": 202,
                    "title": "复查项目",
                    "date": "2025-11-01",
                    "status": "terminated",
                    "status_label": "已中止",
                },
            ],
        },
        {
            "name": "第一疗程",
            "tasks": [
                {
                    "id": 301,
                    "title": "复查项目",
                    "date": "2025-10-09",
                    "status": "completed",
                    "status_label": "已完成",
                },
                {
                    "id": 302,
                    "title": "复查项目",
                    "date": "2025-10-01",
                    "status": "completed",
                    "status_label": "已完成",
                },
            ],
        },
    ]

    context = {
        "cycles": cycles,
        "page_title": "我的复查",
    }
    return render(request, "web_patient/my_examination.html", context)


@auto_wechat_login
@check_patient
@require_membership
def examination_detail(request: HttpRequest, task_id: int) -> HttpResponse:
    patient = request.patient
    task = get_object_or_404(DailyTask, id=task_id, patient=patient)
    reports = TestReport.objects.filter(patient=patient, report_date=task.task_date)

    context = {
        "task": task,
        "reports": reports,
        "page_title": "复查详情",
    }
    return render(request, "web_patient/examination_detail.html", context)
