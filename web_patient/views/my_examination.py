import logging

from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from core.models import DailyTask, TreatmentCycle
from core.models.choices import PlanItemCategory, TaskStatus
from core.service import tasks as task_service
from health_data.models.test_report import TestReport
from users.decorators import auto_wechat_login, check_patient, require_membership

logger = logging.getLogger(__name__)


def _resolve_cycle_for_task(task: DailyTask, cycles):
    if task.plan_item and task.plan_item.cycle:
        return task.plan_item.cycle

    for cycle in cycles:
        end_date = cycle.end_date or timezone.localdate()
        if cycle.start_date <= task.task_date <= end_date:
            return cycle

    return None


def _build_task_payload(task: DailyTask, today):
    status = "not_started"
    status_label = "未开始"

    if task.status == TaskStatus.COMPLETED:
        status = "completed"
        status_label = "已完成"
    elif task.status == TaskStatus.TERMINATED:
        status = "terminated"
        status_label = "已中止"
    elif task.status == TaskStatus.PENDING:
        if task.task_date > today:
            status = "not_started"
            status_label = "未开始"
        else:
            status = "active"
            status_label = "去完成"

    return {
        "id": task.id,
        "title": task.title,
        "date": task.task_date.strftime("%Y-%m-%d"),
        "status": status,
        "status_label": status_label,
    }


@auto_wechat_login
@check_patient
@require_membership
def my_examination(request: HttpRequest) -> HttpResponse:
    """
    我的复查页面
    展示按疗程分组的复查任务列表
    """
    patient = request.patient
    today = timezone.localdate()

    task_service.refresh_task_statuses(
        as_of_date=today,
        patient_id=patient.id,
    )

    cycles = list(TreatmentCycle.objects.filter(patient=patient).order_by("-start_date"))
    tasks = (
        DailyTask.objects.filter(
            patient=patient,
            task_type=PlanItemCategory.CHECKUP,
        )
        .select_related("plan_item", "plan_item__cycle")
        .order_by("-task_date")
    )

    tasks_by_cycle_id = {}
    unassigned_tasks = []

    for task in tasks:
        cycle = _resolve_cycle_for_task(task, cycles)
        if cycle:
            tasks_by_cycle_id.setdefault(cycle.id, []).append(task)
        else:
            unassigned_tasks.append(task)

    cycles_payload = []
    for cycle in cycles:
        cycle_tasks = tasks_by_cycle_id.get(cycle.id, [])
        if not cycle_tasks:
            continue

        is_current = cycle.start_date <= today and (
            cycle.end_date is None or cycle.end_date >= today
        )
        cycle_name = f"{cycle.name} (当前疗程)" if is_current else cycle.name
        cycle_tasks_sorted = sorted(cycle_tasks, key=lambda t: t.task_date, reverse=True)

        cycles_payload.append(
            {
                "name": cycle_name,
                "tasks": [_build_task_payload(task, today) for task in cycle_tasks_sorted],
            }
        )

    if unassigned_tasks:
        cycles_payload.append(
            {
                "name": "其他复查",
                "tasks": [
                    _build_task_payload(task, today)
                    for task in sorted(unassigned_tasks, key=lambda t: t.task_date, reverse=True)
                ],
            }
        )

    if not cycles_payload:
        cycles_payload = [
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
        "cycles": cycles_payload,
        "page_title": "我的复查",
    }
    return render(request, "web_patient/my_examination.html", context)


@auto_wechat_login
@check_patient
@require_membership
def examination_detail(request: HttpRequest, task_id: int) -> HttpResponse:
    """
    复查报告详情页面
    """
    patient = request.patient
    task = get_object_or_404(DailyTask, id=task_id, patient=patient)
    reports = TestReport.objects.filter(patient=patient, report_date=task.task_date)

    context = {
        "task": task,
        "reports": reports,
        "page_title": "复查详情",
    }
    return render(request, "web_patient/examination_detail.html", context)
