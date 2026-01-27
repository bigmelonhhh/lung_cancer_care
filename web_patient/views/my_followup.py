import logging
from django.shortcuts import render
from django.http import HttpRequest, HttpResponse
from users.decorators import auto_wechat_login, check_patient, require_membership

from django.utils import timezone

from core.models import TreatmentCycle, DailyTask, choices
from core.service.treatment_cycle import get_active_treatment_cycle, get_treatment_cycles

logger = logging.getLogger(__name__)


def _resolve_grouped_status(statuses: list[int]) -> tuple[str, str]:
    if choices.TaskStatus.PENDING in statuses:
        return "incomplete", "未完成"
    if choices.TaskStatus.NOT_STARTED in statuses:
        return "not_started", "未开始"
    if choices.TaskStatus.TERMINATED in statuses:
        return "terminated", "已中止"
    if choices.TaskStatus.COMPLETED in statuses:
        return "completed", "已完成"
    return "not_started", "未开始"


def _get_treatment_courses_followup_like_plan(*, patient) -> list[dict]:
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
                    choices.PlanItemCategory.QUESTIONNAIRE,
                ],
                task_date__range=(start_date, end_date),
            )
            .order_by("-task_date", "task_type", "id")
        )

        grouped: dict[tuple[timezone.datetime.date, int], list[int]] = {}
        for task in tasks:
            grouped.setdefault((task.task_date, int(task.task_type)), []).append(
                int(task.status)
            )

        items: list[dict] = []
        for (task_date, task_type), statuses in grouped.items():
            if task_type != choices.PlanItemCategory.QUESTIONNAIRE:
                continue

            status, status_text = _resolve_grouped_status(statuses)
            items.append(
                {
                    "title": "随访问卷",
                    "date": task_date.strftime("%Y-%m-%d"),
                    "status": status,
                    "status_text": status_text,
                    "type": "questionnaire",
                }
            )

        items.sort(
            key=lambda item: (
                item.get("date") or "",
                -(0 if item.get("type") == "questionnaire" else 1),
            ),
            reverse=True,
        )

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
def my_followup(request: HttpRequest) -> HttpResponse:
    """
    我的随访页面
    """
    cycles = []
    error_message = None

    try:
        treatment_courses = _get_treatment_courses_followup_like_plan(patient=request.patient)
        cycles = [
            {
                "name": f"{course['name']} (当前疗程)"
                if course.get("is_current")
                else course.get("name"),
                "tasks": course.get("items") or [],
            }
            for course in treatment_courses
        ]
    except Exception as e:
        logger.error("获取随访问卷列表失败: %s", e, exc_info=True)
        error_message = "随访问卷数据加载失败，请稍后重试。"
        cycles = []

    context = {
        "cycles": cycles,
        "page_title": "我的随访",
        "error_message": error_message,
    }

    return render(request, "web_patient/follow_up.html", context)
