"""患者端管理计划页的展示数据构建。"""

from __future__ import annotations

import logging
from datetime import date

from django.utils import timezone

from core.models import DailyTask, choices
from core.service.treatment_cycle import get_treatment_cycles


logger = logging.getLogger(__name__)


_SECTION_DEFINITIONS = (
    (
        "in_progress",
        "进行中疗程",
        "暂无进行中疗程",
        "当前没有正在执行的复查与随访问卷计划。",
    ),
    (
        "not_started",
        "未开始疗程",
        "暂无未开始疗程",
        "暂未安排后续疗程。",
    ),
    (
        "ended",
        "已结束疗程",
        "暂无已结束疗程",
        "目前没有历史疗程记录。",
    ),
)


def build_empty_treatment_course_sections(
    *,
    empty_subject: str = "复查与随访问卷计划",
) -> list[dict]:
    """返回固定顺序的疗程分区空结构。"""

    sections = []
    for key, title, empty_title, empty_description in _SECTION_DEFINITIONS:
        if key == "in_progress":
            empty_description = f"当前没有正在执行的{empty_subject}。"
        sections.append(
            {
                "key": key,
                "title": title,
                "count": 0,
                "default_open": False,
                "empty_title": empty_title,
                "empty_description": empty_description,
                "courses": [],
            }
        )
    return sections


def _get_all_treatment_cycles(patient) -> list:
    """读取患者全部疗程，兼容疗程服务的分页接口。"""

    cycles_page = get_treatment_cycles(patient, page=1, page_size=100)
    cycles = list(cycles_page.object_list)
    while getattr(cycles_page, "has_next", lambda: False)():
        cycles_page = get_treatment_cycles(
            patient,
            page=int(cycles_page.next_page_number()),
            page_size=100,
        )
        cycles.extend(list(cycles_page.object_list))
    return cycles


def _classify_treatment_cycle(cycle, as_of_date: date) -> tuple[str, str]:
    """按显式状态和日期确定疗程展示分区及状态文案。"""

    if cycle.status == choices.TreatmentCycleStatus.TERMINATED:
        return "ended", "已终止"
    if (
        cycle.status == choices.TreatmentCycleStatus.COMPLETED
        or cycle.end_date < as_of_date
    ):
        return "ended", "已结束"
    if cycle.start_date > as_of_date:
        return "not_started", "未开始"
    return "in_progress", "进行中"


def _build_course_items(patient, cycle, *, task_types: tuple[int, ...]) -> list[dict]:
    """构建单个疗程内按日期合并的复查和随访问卷条目。"""

    tasks = (
        DailyTask.objects.filter(
            patient=patient,
            task_type__in=task_types,
            task_date__range=(cycle.start_date, cycle.end_date),
        )
        .order_by("-task_date", "task_type", "id")
    )

    grouped = {}
    for task in tasks:
        grouped.setdefault((task.task_date, int(task.task_type)), []).append(
            int(task.status)
        )

    items = []
    for (task_date, task_type), statuses in grouped.items():
        if task_type == choices.PlanItemCategory.QUESTIONNAIRE:
            item_type = "questionnaire"
            title = "随访问卷"
        else:
            item_type = "checkup"
            title = "复查"

        status_val = None
        if choices.TaskStatus.PENDING in statuses:
            status_val = choices.TaskStatus.PENDING
        elif choices.TaskStatus.NOT_STARTED in statuses:
            status_val = choices.TaskStatus.NOT_STARTED
        elif choices.TaskStatus.TERMINATED in statuses:
            status_val = choices.TaskStatus.TERMINATED
        elif choices.TaskStatus.COMPLETED in statuses:
            status_val = choices.TaskStatus.COMPLETED

        status = ""
        status_text = ""
        if status_val == choices.TaskStatus.COMPLETED:
            status = "completed"
            status_text = "已完成"
        elif status_val == choices.TaskStatus.PENDING:
            status = "incomplete"
            status_text = "未完成"
        elif status_val == choices.TaskStatus.NOT_STARTED:
            status = "not_started"
            status_text = "未开始"
        elif status_val == choices.TaskStatus.TERMINATED:
            status = "terminated"
            status_text = "已中止"

        items.append(
            {
                "title": title,
                "date": task_date.strftime("%Y-%m-%d"),
                "status": status,
                "status_text": status_text,
                "type": item_type,
            }
        )

    items.sort(
        key=lambda item: (
            item.get("date") or "",
            -(0 if item.get("type") == "questionnaire" else 1),
        ),
        reverse=True,
    )
    return items


def build_treatment_course_sections(
    patient,
    *,
    as_of_date: date | None = None,
    task_types: tuple[int, ...] = (
        choices.PlanItemCategory.CHECKUP,
        choices.PlanItemCategory.QUESTIONNAIRE,
    ),
    empty_subject: str = "复查与随访问卷计划",
    raise_errors: bool = False,
) -> list[dict]:
    """构建固定的进行中、未开始和已结束疗程分区。"""

    sections = build_empty_treatment_course_sections(empty_subject=empty_subject)
    sections_by_key = {section["key"]: section for section in sections}
    as_of_date = as_of_date or timezone.localdate()

    try:
        for cycle in _get_all_treatment_cycles(patient):
            if not cycle.start_date or not cycle.end_date:
                continue

            section_key, status_text = _classify_treatment_cycle(cycle, as_of_date)
            sections_by_key[section_key]["courses"].append(
                {
                    "name": cycle.name,
                    "start_date": cycle.start_date,
                    "end_date": cycle.end_date,
                    "status_text": status_text,
                    "items": _build_course_items(
                        patient,
                        cycle,
                        task_types=task_types,
                    ),
                }
            )
    except Exception:
        if raise_errors:
            raise
        logger.exception(
            "构建患者管理计划疗程分区失败",
            extra={"patient_id": getattr(patient, "id", None)},
        )
        return build_empty_treatment_course_sections(empty_subject=empty_subject)

    sections_by_key["in_progress"]["courses"].sort(
        key=lambda course: (course["start_date"], course["end_date"]),
        reverse=True,
    )
    sections_by_key["not_started"]["courses"].sort(
        key=lambda course: (course["start_date"], course["end_date"]),
    )
    sections_by_key["ended"]["courses"].sort(
        key=lambda course: (course["end_date"], course["start_date"]),
        reverse=True,
    )

    for section in sections:
        section["count"] = len(section["courses"])
        section["default_open"] = bool(
            section["key"] == "in_progress" and section["courses"]
        )

    return sections


def build_checkup_course_sections(patient, *, as_of_date: date | None = None) -> list[dict]:
    """构建仅包含复查任务的疗程分区。"""

    return build_treatment_course_sections(
        patient,
        as_of_date=as_of_date,
        task_types=(choices.PlanItemCategory.CHECKUP,),
        empty_subject="复查计划",
        raise_errors=True,
    )


def build_followup_course_sections(patient, *, as_of_date: date | None = None) -> list[dict]:
    """构建仅包含随访问卷任务的疗程分区。"""

    return build_treatment_course_sections(
        patient,
        as_of_date=as_of_date,
        task_types=(choices.PlanItemCategory.QUESTIONNAIRE,),
        empty_subject="随访问卷计划",
        raise_errors=True,
    )
