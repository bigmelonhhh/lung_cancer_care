from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError

from health_data.services.questionnaire_scoring import (
    is_eq5d5l_code,
    is_eqvas_code,
)
from patient_alerts.models import AlertEventType, AlertLevel, PatientAlert
from patient_alerts.services.alert_sources import PatientAlertSourceService
from patient_alerts.services.patient_alert import PatientAlertService
from health_data.models import QuestionnaireSubmission

logger = logging.getLogger(__name__)


class QuestionnaireAlertService:
    """
    【功能说明】
    - 根据问卷提交结果生成异常报警。
    - 仅对轻/中/重等级触发待办。
    """

    GRADE_TO_LEVEL = {
        2: AlertLevel.MILD,
        3: AlertLevel.MODERATE,
        4: AlertLevel.SEVERE,
    }
    GRADE_LABELS = {
        2: "轻度",
        3: "中度",
        4: "重度",
    }

    @classmethod
    def process_submission(
        cls, submission: QuestionnaireSubmission
    ) -> PatientAlert | None:
        """
        处理问卷提交并生成报警。

        【参数说明】
        - submission: QuestionnaireSubmission 问卷提交记录。

        【返回值说明】
        - PatientAlert | None：未触发报警返回 None。
        """
        if not submission:
            return None

        try:
            from health_data.services.questionnaire_submission import (
                QuestionnaireSubmissionService,
            )

            grade_result = (
                QuestionnaireSubmissionService.get_submission_grade_result(
                    submission.id
                )
            )
        except ValidationError:
            return None
        except Exception:
            logger.exception(
                "问卷分级失败，未生成预警。submission_id=%s",
                submission.id,
            )
            return None

        grade_level = grade_result.grade_level
        alert_level = cls.GRADE_TO_LEVEL.get(grade_level)
        if not alert_level:
            return None

        total_score = submission.total_score or Decimal("0")
        payload: dict[str, Any] = {
            "submission_id": submission.id,
            "questionnaire_id": submission.questionnaire_id,
            "questionnaire_code": submission.questionnaire.code,
            "total_score": str(total_score),
            "grade_level": grade_level,
        }
        questionnaire_code = submission.questionnaire.code
        if is_eq5d5l_code(questionnaire_code):
            payload.update(grade_result.details)
            payload["grading_rule"] = grade_result.rule_version
            max_dimensions = "、".join(
                grade_result.details["max_dimensions"]
            )
            title = "EQ-5D-5L量表异常"
            content = (
                f"健康状态{grade_result.details['health_state']}，"
                f"健康效用指数{grade_result.details['utility_index']}，"
                f"最严重维度为{max_dimensions}"
                f"（{grade_result.details['max_dimension_level']}级）。"
            )
            value_display = content
        elif is_eqvas_code(questionnaire_code):
            payload.update(grade_result.details)
            payload["grading_rule"] = grade_result.rule_version
            vas_score = grade_result.details["vas_score"]
            title = "EQ-VAS评分异常"
            content = (
                f"EQ-VAS评分{vas_score}分，"
                f"当前为{grade_level}级{cls.GRADE_LABELS[grade_level]}。"
            )
            value_display = content
        else:
            title = f"{submission.questionnaire.name}异常"
            content = f"总分 {total_score}，分级 {grade_level} 级"
            value_display = None

        alert = PatientAlertService.create_or_update_alert(
            patient_id=submission.patient_id,
            event_type=AlertEventType.QUESTIONNAIRE,
            event_level=alert_level,
            event_title=title,
            event_content=content,
            event_time=submission.created_at,
            source_type="questionnaire",
            source_id=submission.id,
            source_payload=payload,
            dedup_filters={
                "event_title": title,
                "source_type": "questionnaire",
            },
        )
        PatientAlertSourceService.record_questionnaire_source(
            alert=alert,
            submission=submission,
            event_level=alert_level,
            grade_level=grade_level,
            total_score=total_score,
            source_payload=payload,
            value_display=value_display,
        )
        return alert
