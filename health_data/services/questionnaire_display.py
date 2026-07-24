"""Data-driven questionnaire presentation and reporting helpers."""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Count, OuterRef, Q, Subquery
from django.db.models.functions import TruncMonth
from django.utils import timezone

from core.models import Questionnaire, choices
from health_data.models import QuestionnaireSubmission
from health_data.services.questionnaire_scoring import is_eq5d5l_code, is_eqvas_code
from patient_alerts.services.todo_list import TodoListService


class QuestionnaireDisplayService:
    """Build questionnaire view models shared by patient and doctor pages."""

    @staticmethod
    def _score_label(questionnaire_code: str | None) -> str:
        if is_eq5d5l_code(questionnaire_code):
            return "健康效用指数"
        if is_eqvas_code(questionnaire_code):
            return "EQ-VAS评分"
        return "问卷评分"

    COLOR_PALETTE = (
        "#3B82F6",
        "#8B5CF6",
        "#F59E0B",
        "#10B981",
        "#EC4899",
        "#06B6D4",
        "#6366F1",
        "#14B8A6",
    )
    ICON_RULES = (
        (("呼吸", "breath", "dyspnea"), "breath"),
        (("咳嗽", "咯血", "痰", "cough"), "cough"),
        (("疼痛", "痛", "pain"), "pain"),
        (("睡眠", "sleep"), "sleep"),
        (("食欲", "饮食", "营养", "appetite", "diet"), "appetite"),
        (("焦虑", "抑郁", "心理", "情绪", "anxiety", "psych", "depress"), "psych"),
        (("口腔", "黏膜", "mucosa", "oral"), "oral_mucosa"),
        (("体能", "活动", "physical", "stamina"), "physical"),
    )

    @classmethod
    def _active_questionnaires(cls, *, with_questions: bool = False):
        queryset = Questionnaire.objects.filter(is_active=True).order_by(
            "sort_order", "name", "id"
        )
        if with_questions:
            queryset = queryset.prefetch_related("questions__options")
        return queryset

    @classmethod
    def resolve_visual(cls, questionnaire: Questionnaire) -> dict[str, str]:
        """Resolve a safe icon key and deterministic palette color."""
        semantic_text = f"{questionnaire.name} {questionnaire.code}".lower()
        icon_key = "questionnaire"
        for keywords, candidate in cls.ICON_RULES:
            if any(keyword.lower() in semantic_text for keyword in keywords):
                icon_key = candidate
                break
        color = cls.COLOR_PALETTE[(questionnaire.id or 0) % len(cls.COLOR_PALETTE)]
        return {"icon_key": icon_key, "color": color}

    @classmethod
    def build_patient_archive_cards(
        cls,
        *,
        patient,
        start_at: datetime,
        end_at: datetime,
    ) -> list[dict[str, Any]]:
        """Return active questionnaires submitted by a patient in ``[start, end)``."""
        submissions = QuestionnaireSubmission.objects.filter(
            patient=patient,
            questionnaire=OuterRef("pk"),
            created_at__gte=start_at,
            created_at__lt=end_at,
        )
        questionnaires = list(
            cls._active_questionnaires()
            .annotate(
                submission_count=Count(
                    "submissions",
                    filter=Q(
                        submissions__patient=patient,
                        submissions__created_at__gte=start_at,
                        submissions__created_at__lt=end_at,
                    ),
                    distinct=True,
                ),
                latest_score=Subquery(
                    submissions.order_by("-created_at", "-id").values("total_score")[:1]
                ),
            )
            .filter(submission_count__gt=0)
        )
        abnormal_counts = TodoListService.count_questionnaire_abnormal_events(
            patient=patient,
            start_at=start_at,
            end_at=end_at,
            questionnaire_codes=[
                questionnaire.code for questionnaire in questionnaires
            ],
        )

        cards = []
        for questionnaire in questionnaires:
            visual = cls.resolve_visual(questionnaire)
            cards.append(
                {
                    "questionnaire_id": questionnaire.id,
                    "code": questionnaire.code,
                    "name": questionnaire.name,
                    "title": questionnaire.name,
                    "submission_count": questionnaire.submission_count,
                    "count": questionnaire.submission_count,
                    "latest_score": questionnaire.latest_score,
                    "score_label": cls._score_label(questionnaire.code),
                    "icon_key": visual["icon_key"],
                    "color": visual["color"],
                    "abnormal": abnormal_counts.get(questionnaire.code, 0),
                }
            )
        return cards

    @classmethod
    def _score_bounds(
        cls,
        questionnaire: Questionnaire,
        actual_scores: list[float],
    ) -> tuple[float, float]:
        if is_eq5d5l_code(questionnaire.code):
            return -0.4, 1.0
        if is_eqvas_code(questionnaire.code):
            return 0.0, 100.0

        theoretical_min = Decimal("0")
        theoretical_max = Decimal("0")
        for question in questionnaire.questions.all():
            scores = [option.score for option in question.options.all()]
            if not scores or question.q_type == choices.QuestionType.TEXT:
                continue
            if question.q_type == choices.QuestionType.MULTIPLE:
                question_min = sum((score for score in scores if score < 0), Decimal("0"))
                question_max = sum((score for score in scores if score > 0), Decimal("0"))
            else:
                candidates = scores if question.is_required else [Decimal("0"), *scores]
                question_min = min(candidates)
                question_max = max(candidates)
            theoretical_min += question_min
            theoretical_max += question_max

        if theoretical_min == theoretical_max == 0 and not actual_scores:
            return 0.0, 10.0

        candidates = [float(theoretical_min), float(theoretical_max), *actual_scores]
        lower = min(candidates, default=0.0)
        upper = max(candidates, default=10.0)
        if lower > 0:
            lower = 0.0
        if upper <= lower:
            upper = lower + 10.0
        padding = max(2.0, (upper - lower) * 0.2)
        return float(math.floor(lower)), float(math.ceil(upper + padding))

    @classmethod
    def build_daily_score_charts(
        cls,
        *,
        patient,
        start_at: datetime,
        end_at: datetime,
        date_list: list[date],
    ) -> list[dict[str, Any]]:
        """Build one daily score chart for every active questionnaire."""
        questionnaires = list(cls._active_questionnaires(with_questions=True))
        active_ids = [questionnaire.id for questionnaire in questionnaires]
        latest_by_questionnaire_day: dict[tuple[int, date], Decimal | None] = {}
        submissions = QuestionnaireSubmission.objects.filter(
            patient=patient,
            questionnaire_id__in=active_ids,
            created_at__gte=start_at,
            created_at__lt=end_at,
        ).order_by("created_at", "id")
        for submission in submissions:
            local_day = timezone.localtime(submission.created_at).date()
            latest_by_questionnaire_day[(submission.questionnaire_id, local_day)] = (
                submission.total_score
            )

        charts = []
        date_labels = [item.strftime("%m-%d") for item in date_list]
        for questionnaire in questionnaires:
            data = []
            actual_scores = []
            for target_day in date_list:
                score = latest_by_questionnaire_day.get((questionnaire.id, target_day))
                value = float(score) if score is not None else None
                data.append(value)
                if value is not None:
                    actual_scores.append(value)
            y_min, y_max = cls._score_bounds(questionnaire, actual_scores)
            visual = cls.resolve_visual(questionnaire)
            charts.append(
                {
                    "questionnaire_id": questionnaire.id,
                    "code": questionnaire.code,
                    "name": questionnaire.name,
                    "id": f"chart-questionnaire-{questionnaire.id}",
                    "data_script_id": f"questionnaire-chart-data-{questionnaire.id}",
                    "title": questionnaire.name,
                    "subtitle": f"({len(actual_scores)}次)",
                    "dates": date_labels,
                    "y_min": y_min,
                    "y_max": y_max,
                    "icon_key": visual["icon_key"],
                    "color": visual["color"],
                    "series": [
                        {
                            "name": cls._score_label(questionnaire.code),
                            "data": data,
                            "data_json": json.dumps(data, ensure_ascii=False),
                            "missing": [1 if value is None else 0 for value in data],
                            "color": visual["color"],
                        }
                    ],
                }
            )
        return charts

    @classmethod
    def build_monthly_count_charts(
        cls,
        *,
        patient,
        start_date: date | None,
        end_date: date | None,
        month_labels: list[str],
    ) -> list[dict[str, Any]]:
        """Build monthly submission-count charts for every active questionnaire."""
        questionnaires = list(cls._active_questionnaires())
        counts: dict[tuple[int, str], int] = {}
        if start_date and end_date and questionnaires:
            tz = timezone.get_current_timezone()
            start_at = timezone.make_aware(
                datetime.combine(start_date, datetime.min.time()), tz
            )
            end_at = timezone.make_aware(
                datetime.combine(end_date + timedelta(days=1), datetime.min.time()), tz
            )
            rows = (
                QuestionnaireSubmission.objects.filter(
                    patient=patient,
                    questionnaire_id__in=[item.id for item in questionnaires],
                    created_at__gte=start_at,
                    created_at__lt=end_at,
                )
                .annotate(month=TruncMonth("created_at"))
                .values("questionnaire_id", "month")
                .annotate(count=Count("id"))
            )
            for row in rows:
                month_value = timezone.localtime(row["month"]).strftime("%Y-%m")
                counts[(row["questionnaire_id"], month_value)] = row["count"]

        charts = []
        for questionnaire in questionnaires:
            data = [counts.get((questionnaire.id, month), 0) for month in month_labels]
            total = sum(data)
            visual = cls.resolve_visual(questionnaire)
            charts.append(
                {
                    "questionnaire_id": questionnaire.id,
                    "code": questionnaire.code,
                    "name": questionnaire.name,
                    "id": f"chart-questionnaire-count-{questionnaire.id}",
                    "data_script_id": f"questionnaire-count-chart-data-{questionnaire.id}",
                    "title": f"{questionnaire.name}统计次数: {total}次",
                    "subtitle": "",
                    "dates": month_labels,
                    "y_min": 0,
                    "y_max": max(data) + 5 if data else 10,
                    "submission_count": total,
                    "icon_key": visual["icon_key"],
                    "color": visual["color"],
                    "series": [
                        {
                            "name": "统计次数",
                            "data": data,
                            "color": visual["color"],
                        }
                    ],
                }
            )
        return charts

    @classmethod
    def list_patient_submissions(
        cls,
        *,
        patient,
        questionnaire_id: int,
        start_at: datetime,
        end_at: datetime,
        cursor_month: str,
        cursor_offset: int,
        limit: int,
    ) -> tuple[list[dict[str, Any]], bool, str | None, int | None]:
        """Load questionnaire submissions backwards across package months."""
        package_queryset = QuestionnaireSubmission.objects.filter(
            patient=patient,
            questionnaire_id=questionnaire_id,
            created_at__gte=start_at,
            created_at__lt=end_at,
        )
        earliest_submission = package_queryset.order_by("created_at", "id").first()
        if earliest_submission is None:
            return [], False, None, None
        questionnaire_code = (
            Questionnaire.objects.filter(pk=questionnaire_id)
            .values_list("code", flat=True)
            .first()
        )

        tz = timezone.get_current_timezone()
        earliest_month = timezone.localtime(earliest_submission.created_at).date().replace(day=1)
        package_end_month = timezone.localtime(
            end_at - timedelta(microseconds=1)
        ).date().replace(day=1)
        try:
            active_month = datetime.strptime(cursor_month, "%Y-%m").date().replace(day=1)
        except (TypeError, ValueError):
            active_month = package_end_month
        active_month = min(active_month, package_end_month)
        active_offset = max(0, cursor_offset)

        submissions = []
        next_month = active_month
        while len(submissions) < limit and next_month >= earliest_month:
            month_start_at = timezone.make_aware(
                datetime.combine(next_month, datetime.min.time()), tz
            )
            if next_month.month == 12:
                following_month = date(next_month.year + 1, 1, 1)
            else:
                following_month = date(next_month.year, next_month.month + 1, 1)
            month_end_at = timezone.make_aware(
                datetime.combine(following_month, datetime.min.time()), tz
            )
            window_start = max(start_at, month_start_at)
            window_end = min(end_at, month_end_at)
            month_queryset = package_queryset.filter(
                created_at__gte=window_start,
                created_at__lt=window_end,
            ).order_by("-created_at", "-id")
            month_total = month_queryset.count()
            if active_offset >= month_total:
                next_month = (
                    date(next_month.year - 1, 12, 1)
                    if next_month.month == 1
                    else date(next_month.year, next_month.month - 1, 1)
                )
                active_offset = 0
                continue

            remaining = limit - len(submissions)
            month_items = list(
                month_queryset[active_offset : active_offset + remaining]
            )
            submissions.extend(month_items)
            next_offset = active_offset + len(month_items)
            if next_offset < month_total:
                return (
                    cls._serialize_patient_submissions(
                        submissions,
                        questionnaire_code=questionnaire_code,
                    ),
                    True,
                    next_month.strftime("%Y-%m"),
                    next_offset,
                )

            next_month = (
                date(next_month.year - 1, 12, 1)
                if next_month.month == 1
                else date(next_month.year, next_month.month - 1, 1)
            )
            active_offset = 0

        has_more = bool(submissions) and next_month >= earliest_month
        return (
            cls._serialize_patient_submissions(
                submissions,
                questionnaire_code=questionnaire_code,
            ),
            has_more,
            next_month.strftime("%Y-%m") if has_more else None,
            0 if has_more else None,
        )

    @staticmethod
    def _serialize_patient_submissions(
        submissions: list[QuestionnaireSubmission],
        *,
        questionnaire_code: str | None,
    ) -> list[dict[str, Any]]:
        """Convert submission rows to the existing health-record card shape."""
        records = []
        weekday_labels = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")
        score_label = QuestionnaireDisplayService._score_label(questionnaire_code)
        for submission in submissions:
            submitted_at = timezone.localtime(submission.created_at)
            records.append(
                {
                    "id": submission.id,
                    "questionnaire_submission_id": submission.id,
                    "score": submission.total_score,
                    "date": submitted_at.strftime("%Y-%m-%d"),
                    "weekday": weekday_labels[submitted_at.weekday()],
                    "time": submitted_at.strftime("%H:%M"),
                    "source": "questionnaire",
                    "source_display": "患者填写",
                    "is_manual": False,
                    "can_edit": False,
                    "can_operate": False,
                    "data": [
                        {
                            "label": score_label,
                            "value": submission.total_score
                            if submission.total_score is not None
                            else "-",
                            "is_large": True,
                            "key": "questionnaire_score",
                        }
                    ],
                }
            )
        return records

    @classmethod
    def build_patient_month_score_chart(
        cls,
        *,
        patient,
        questionnaire: Questionnaire,
        start_at: datetime,
        end_at: datetime,
        date_list: list[date],
    ) -> dict[str, Any]:
        """Build a single questionnaire score chart for a patient archive month."""
        latest_by_day: dict[date, Decimal | None] = {}
        submissions = QuestionnaireSubmission.objects.filter(
            patient=patient,
            questionnaire=questionnaire,
            created_at__gte=start_at,
            created_at__lt=end_at,
        ).order_by("created_at", "id")
        for submission in submissions:
            latest_by_day[timezone.localtime(submission.created_at).date()] = (
                submission.total_score
            )

        actual_scores = [
            float(score) for score in latest_by_day.values() if score is not None
        ]
        questionnaire_with_options = (
            cls._active_questionnaires(with_questions=True)
            .filter(pk=questionnaire.pk)
            .first()
        )
        bounds_source = questionnaire_with_options or questionnaire
        y_min, y_max = cls._score_bounds(bounds_source, actual_scores)
        values = []
        for target_day in date_list:
            score = latest_by_day.get(target_day)
            raw_value = float(score) if score is not None else None
            values.append(
                {
                    "value": raw_value if raw_value is not None else 0,
                    "raw_value": raw_value,
                    "is_no_task": False,
                }
            )
        visual = cls.resolve_visual(questionnaire)
        return {
            "dates": [item.strftime("%m-%d") for item in date_list],
            "series": [
                {
                    "name": (
                        cls._score_label(questionnaire.code)
                        if is_eq5d5l_code(questionnaire.code)
                        or is_eqvas_code(questionnaire.code)
                        else questionnaire.name
                    ),
                    "data": values,
                    "color": visual["color"],
                }
            ],
            "y_min": y_min,
            "y_max": y_max,
        }
