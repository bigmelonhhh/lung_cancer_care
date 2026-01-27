import logging

from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from core.models import DailyTask, TreatmentCycle
from core.models.choices import PlanItemCategory, TaskStatus
from core.service import tasks as task_service
from core.service.treatment_cycle import get_active_treatment_cycle, get_treatment_cycles
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
            status_label = "未完成"

    return {
        "id": task.id,
        "title": task.title,
        "date": task.task_date.strftime("%Y-%m-%d"),
        "status": status,
        "status_label": status_label,
    }


def _resolve_grouped_status(statuses: list[int]) -> int | None:
    if TaskStatus.PENDING in statuses:
        return TaskStatus.PENDING
    if TaskStatus.NOT_STARTED in statuses:
        return TaskStatus.NOT_STARTED
    if TaskStatus.TERMINATED in statuses:
        return TaskStatus.TERMINATED
    if TaskStatus.COMPLETED in statuses:
        return TaskStatus.COMPLETED
    return None


def _get_treatment_courses_checkup_like_my_followup(*, patient, today) -> list[dict]:
    active_cycle = get_active_treatment_cycle(patient)

    cycles_page = get_treatment_cycles(patient, page=1, page_size=100)
    cycles = list(cycles_page.object_list)
    while getattr(cycles_page, "has_next", lambda: False)():
        cycles_page = get_treatment_cycles(
            patient, page=int(cycles_page.next_page_number()), page_size=100
        )
        cycles.extend(list(cycles_page.object_list))

    treatment_courses: list[dict] = []
    for cycle in cycles:
        start_date = getattr(cycle, "start_date", None)
        end_date = getattr(cycle, "end_date", None)
        if not start_date or not end_date:
            continue

        tasks = (
            DailyTask.objects.filter(
                patient=patient,
                task_type__in=[
                    PlanItemCategory.CHECKUP,
                ],
                task_date__range=(start_date, end_date),
            )
            .order_by("-task_date", "task_type", "id")
        )

        grouped: dict[tuple[timezone.datetime.date, int], dict] = {}
        for task in tasks:
            key = (task.task_date, int(task.task_type))
            if key not in grouped:
                grouped[key] = {"task_id": int(task.id), "statuses": []}
            grouped[key]["statuses"].append(int(task.status))

        items: list[dict] = []
        for (task_date, task_type), payload in grouped.items():
            if task_type != PlanItemCategory.CHECKUP:
                continue

            status_val = _resolve_grouped_status(payload["statuses"])
            status = ""
            status_label = ""

            if status_val == TaskStatus.COMPLETED:
                status = "completed"
                status_label = "已完成"
            elif status_val == TaskStatus.TERMINATED:
                status = "terminated"
                status_label = "已中止"
            elif status_val == TaskStatus.NOT_STARTED:
                status = "not_started"
                status_label = "未开始"
            elif status_val == TaskStatus.PENDING:
                if task_date > today:
                    status = "not_started"
                    status_label = "未开始"
                else:
                    status = "active"
                    status_label = "未完成"
            else:
                status = "not_started"
                status_label = "未开始"

            items.append(
                {
                    "id": payload["task_id"],
                    "title": "复查",
                    "date": task_date.strftime("%Y-%m-%d"),
                    "status": status,
                    "status_label": status_label,
                }
            )

        items.sort(key=lambda item: (item.get("date") or ""), reverse=True)

        treatment_courses.append(
            {
                "name": cycle.name,
                "is_current": bool(active_cycle and cycle.id == active_cycle.id),
                "items": items,
            }
        )

    return treatment_courses


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

    treatment_courses = _get_treatment_courses_checkup_like_my_followup(
        patient=patient, today=today
    )
    cycles_payload = [
        {
            "name": f"{course['name']} (当前疗程)"
            if course.get("is_current")
            else course.get("name"),
            "tasks": course.get("items") or [],
        }
        for course in treatment_courses
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
