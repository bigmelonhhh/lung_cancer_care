import logging

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone

from core.service import tasks as task_service
from users.decorators import auto_wechat_login, check_patient, require_membership
from web_patient.services.management_plan import (
    build_checkup_course_sections,
    build_empty_treatment_course_sections,
)


logger = logging.getLogger(__name__)


@auto_wechat_login
@check_patient
@require_membership
def my_examination(request: HttpRequest) -> HttpResponse:
    """展示患者按疗程分组的复查任务。"""

    patient = request.patient
    today = timezone.localdate()
    error_message = None

    try:
        task_service.refresh_task_statuses(
            as_of_date=today,
            patient_id=patient.id,
        )
        treatment_course_sections = build_checkup_course_sections(
            patient,
            as_of_date=today,
        )
    except Exception:
        logger.exception(
            "获取患者复查列表失败",
            extra={"patient_id": patient.id},
        )
        error_message = "复查数据加载失败，请稍后重试。"
        treatment_course_sections = build_empty_treatment_course_sections(
            empty_subject="复查计划"
        )

    context = {
        "treatment_course_sections": treatment_course_sections,
        "page_title": "我的复查",
        "course_empty_message": "该疗程暂无复查计划",
        "error_message": error_message,
    }
    return render(request, "web_patient/my_examination.html", context)
