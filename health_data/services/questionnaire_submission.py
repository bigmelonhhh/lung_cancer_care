"""问卷提交业务逻辑服务。"""

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Prefetch
from django.utils import timezone

from core.models import (
    Questionnaire,
    QuestionnaireCode,
    QuestionnaireOption,
    QuestionnaireQuestion,
)
from core.models.choices import QuestionType
from core.service import tasks as task_service
from health_data.models import QuestionnaireAnswer, QuestionnaireSubmission
from health_data.services.health_metric import HealthMetricService
from health_data.services.questionnaire_scoring import (
    Eq5d5lChinaCalculator,
    EqVasCalculator,
    QuestionnaireGradeResult,
    is_eq5d5l_code,
    is_eqvas_code,
)
from patient_alerts.services.questionnaire_alerts import QuestionnaireAlertService

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from users.models import PatientProfile


class QuestionnaireSubmissionService:
    """处理问卷提交、算分及指标落库。"""

    COUGH_BLOOD_QUESTION_ID = 40
    MAX_TEXT_ANSWER_LENGTH = 2000
    EQ5D5L_QUESTION_COUNT = 5
    EQVAS_QUESTION_COUNT = 1
    SLEEP_T_SCORE_MAP = {
        8: Decimal("30.5"),
        9: Decimal("35.3"),
        10: Decimal("38.1"),
        11: Decimal("40.4"),
        12: Decimal("42.2"),
        13: Decimal("43.9"),
        14: Decimal("45.3"),
        15: Decimal("46.7"),
        16: Decimal("47.9"),
        17: Decimal("49.1"),
        18: Decimal("50.2"),
        19: Decimal("51.3"),
        20: Decimal("52.4"),
        21: Decimal("53.4"),
        22: Decimal("54.3"),
        23: Decimal("55.3"),
        24: Decimal("56.2"),
        25: Decimal("57.2"),
        26: Decimal("58.1"),
        27: Decimal("59.1"),
        28: Decimal("60.0"),
        29: Decimal("61.0"),
        30: Decimal("62.0"),
        31: Decimal("63.0"),
        32: Decimal("64.0"),
        33: Decimal("65.1"),
        34: Decimal("66.2"),
        35: Decimal("67.4"),
        36: Decimal("68.7"),
        37: Decimal("70.2"),
        38: Decimal("72.0"),
        39: Decimal("74.1"),
        40: Decimal("77.5"),
    }

    @classmethod
    @transaction.atomic
    def submit_questionnaire(
        cls,
        patient_id: int,
        questionnaire_id: int,
        answers_data: list[dict[str, Any]],
        task_id: int | None = None,
    ) -> QuestionnaireSubmission:
        """
        校验并保存一次问卷提交。

        选择题答案使用 ``option_id``，填空题答案使用
        ``question_id + value_text``。普通 ``SUM`` 问卷只累加选项分；
        ``Q_EQ5D5L`` 使用中国大陆价值集计分，``Q_EQVAS`` 直接使用
        患者填写的 0 至 100 整数。
        所有业务校验均在创建提交记录前完成。
        """
        if not isinstance(answers_data, list):
            raise ValidationError("答案列表格式错误。")

        questionnaire = Questionnaire.objects.get(id=questionnaire_id)
        questions = list(
            QuestionnaireQuestion.objects.filter(questionnaire=questionnaire)
            .only("id", "questionnaire_id", "q_type", "is_required", "seq")
            .order_by("seq", "id")
        )
        if not questions:
            raise ValidationError("当前问卷未配置题目。")
        if not answers_data and not is_eqvas_code(questionnaire.code):
            raise ValidationError("答案列表不能为空。")

        questions_map = {question.id: question for question in questions}
        option_ids: list[int] = []
        text_answers_by_question: dict[int, str] = {}
        for item in answers_data:
            if not isinstance(item, dict):
                raise ValidationError("答案项格式错误。")

            has_option = item.get("option_id") not in (None, "")
            has_text_fields = "question_id" in item or "value_text" in item
            if has_option == has_text_fields:
                raise ValidationError("答案项必须且只能包含选项答案或文本答案。")

            if has_option:
                option_id = item["option_id"]
                if isinstance(option_id, bool):
                    raise ValidationError("选项ID格式错误。")
                try:
                    option_id = int(option_id)
                except (TypeError, ValueError) as exc:
                    raise ValidationError("选项ID格式错误。") from exc
                if option_id <= 0:
                    raise ValidationError("选项ID格式错误。")
                option_ids.append(option_id)
                continue

            question_id = item.get("question_id")
            if isinstance(question_id, bool):
                raise ValidationError("题目ID格式错误。")
            try:
                question_id = int(question_id)
            except (TypeError, ValueError) as exc:
                raise ValidationError("文本答案缺少有效的题目ID。") from exc
            question = questions_map.get(question_id)
            if question is None:
                raise ValidationError("文本答案中包含不属于该问卷的题目。")
            if question.q_type != QuestionType.TEXT:
                raise ValidationError("只有问答/填空题可以提交文本答案。")
            if question_id in text_answers_by_question:
                raise ValidationError("同一道问答/填空题不能重复提交。")

            value_text = item.get("value_text")
            if not isinstance(value_text, str):
                raise ValidationError("问答/填空题答案必须为文本。")
            if len(value_text) > cls.MAX_TEXT_ANSWER_LENGTH:
                raise ValidationError(
                    f"问答/填空题答案不能超过 {cls.MAX_TEXT_ANSWER_LENGTH} 个字符。"
                )
            text_answers_by_question[question_id] = value_text

        if len(option_ids) != len(set(option_ids)):
            raise ValidationError("同一选项不能重复提交。")

        options_qs = (
            QuestionnaireOption.objects.select_related("question")
            .filter(id__in=option_ids)
            .order_by("question__seq", "question_id", "seq", "id")
        )
        options_map = {opt.id: opt for opt in options_qs}
        if len(options_map) != len(option_ids):
            raise ValidationError("存在无效的选项，请检查填写内容。")

        answers_by_question: dict[int, list[QuestionnaireOption]] = {}
        for opt_id in option_ids:
            option = options_map[opt_id]
            if option.question.questionnaire_id != questionnaire.id:
                raise ValidationError("答案中包含不属于该问卷的选项。")
            question = questions_map[option.question_id]
            if question.q_type == QuestionType.TEXT:
                raise ValidationError("问答/填空题不能提交选项答案。")
            answers_by_question.setdefault(question.id, []).append(option)

        for question in questions:
            selected_options = answers_by_question.get(question.id, [])
            text_value = text_answers_by_question.get(question.id)
            has_text_answer = bool(text_value and text_value.strip())

            if question.q_type == QuestionType.SINGLE and len(selected_options) > 1:
                raise ValidationError("单选题只能选择一个选项。")
            if question.q_type == QuestionType.TEXT:
                if selected_options:
                    raise ValidationError("问答/填空题不能提交选项答案。")
                if text_value is not None and not has_text_answer:
                    if question.is_required:
                        raise ValidationError("请完成所有必填题目后再提交。")
                    text_answers_by_question.pop(question.id, None)
            elif question.q_type not in (
                QuestionType.SINGLE,
                QuestionType.MULTIPLE,
            ):
                raise ValidationError("问卷包含不支持的题目类型。")

            is_answered = (
                has_text_answer
                if question.q_type == QuestionType.TEXT
                else bool(selected_options)
            )
            if question.is_required and not is_answered:
                raise ValidationError("请完成所有必填题目后再提交。")

        if is_eq5d5l_code(questionnaire.code):
            total_score = cls._calculate_eq5d5l_score(
                questions=questions,
                answers_by_question=answers_by_question,
            )
        elif is_eqvas_code(questionnaire.code):
            total_score = cls._calculate_eqvas_score(
                questions=questions,
                text_answers_by_question=text_answers_by_question,
            )
        else:
            total_score = Decimal("0.00")
            if questionnaire.calculation_strategy == "SUM":
                total_score = sum(
                    (
                        option.score
                        for selected_options in answers_by_question.values()
                        for option in selected_options
                    ),
                    Decimal("0.00"),
                )

        submission = QuestionnaireSubmission.objects.create(
            patient_id=patient_id,
            questionnaire=questionnaire,
            task_id=task_id,
        )

        answers_to_create = []
        for question in questions:
            for option in answers_by_question.get(question.id, []):
                answers_to_create.append(
                    QuestionnaireAnswer(
                        submission=submission,
                        question=question,
                        option=option,
                    )
                )
            if question.id in text_answers_by_question:
                answers_to_create.append(
                    QuestionnaireAnswer(
                        submission=submission,
                        question=question,
                        option=None,
                        value_text=text_answers_by_question[question.id],
                    )
                )

        QuestionnaireAnswer.objects.bulk_create(answers_to_create)
        submission.total_score = total_score
        submission.save(update_fields=["total_score"])
        _, resolved_task_id = task_service.complete_daily_questionnaire_tasks(
            patient_id=patient_id,
            occurred_at=submission.created_at,
        )
        if submission.task_id is None and resolved_task_id:
            submission.task_id = resolved_task_id
            submission.save(update_fields=["task_id"])

        HealthMetricService.save_manual_metric(
            patient_id=patient_id,
            metric_type=questionnaire.code,
            measured_at=submission.created_at,
            value_main=total_score,
            questionnaire_submission_id=submission.id,
            task_id=submission.task_id,
        )

        try:
            QuestionnaireAlertService.process_submission(submission)
        except Exception:
            logger.exception(
                "问卷 %s 提交成功，但同步报警失败。submission_id=%s",
                questionnaire.name,
                submission.id,
            )

        return submission

    @classmethod
    def _calculate_eq5d5l_score(
        cls,
        *,
        questions: list[QuestionnaireQuestion],
        answers_by_question: dict[int, list[QuestionnaireOption]],
    ) -> Decimal:
        """校验固定五维配置，并计算 EQ-5D-5L 中国大陆健康效用指数。"""
        if len(questions) != cls.EQ5D5L_QUESTION_COUNT:
            raise ValidationError("EQ-5D-5L 问卷必须恰好配置五道题。")

        if any(
            question.q_type != QuestionType.SINGLE
            for question in questions
        ):
            raise ValidationError("EQ-5D-5L 五个健康维度必须均为单选题。")

        configured_values_by_question: dict[int, list[str]] = {}
        for question_id, value in QuestionnaireOption.objects.filter(
            question_id__in=[question.id for question in questions]
        ).values_list("question_id", "value"):
            configured_values_by_question.setdefault(question_id, []).append(value)

        expected_values = {"1", "2", "3", "4", "5"}
        for question in questions:
            configured_values = configured_values_by_question.get(question.id, [])
            if (
                len(configured_values) != len(expected_values)
                or set(configured_values) != expected_values
            ):
                raise ValidationError(
                    "EQ-5D-5L 每个健康维度必须完整配置 1 至 5 五个等级。"
                )

        levels: list[int] = []
        for question in questions:
            selected_options = answers_by_question.get(question.id, [])
            if len(selected_options) != 1:
                raise ValidationError("EQ-5D-5L 五个健康维度必须各选择一个选项。")
            option_value = selected_options[0].value
            if option_value not in {"1", "2", "3", "4", "5"}:
                raise ValidationError(
                    "EQ-5D-5L 健康维度选项值必须为 1 至 5 的整数。"
                )
            levels.append(int(option_value))

        return Eq5d5lChinaCalculator.calculate(levels)

    @classmethod
    def _calculate_eqvas_score(
        cls,
        *,
        questions: list[QuestionnaireQuestion],
        text_answers_by_question: dict[int, str],
    ) -> Decimal:
        """校验单题配置，并返回 EQ-VAS 的 0 至 100 整数评分。"""
        if len(questions) != cls.EQVAS_QUESTION_COUNT:
            raise ValidationError("EQ-VAS 问卷必须恰好配置一道题。")

        question = questions[0]
        if question.q_type != QuestionType.TEXT:
            raise ValidationError("EQ-VAS 问卷题目必须为问答/填空题。")

        vas_value = text_answers_by_question.get(question.id)
        return EqVasCalculator.calculate(vas_value)

    @classmethod
    def get_submission_dates(
        cls,
        *,
        patient: "PatientProfile",
        start_date: date,
        end_date: date,
    ) -> list[date]:
        """
        查询患者在指定日期范围内提交问卷的日期列表（按日期倒序）。

        【功能说明】
        - 在闭区间 [start_date, end_date] 内筛选问卷提交记录；
        - 按本地时区归并到自然日，同一天多次提交只保留一天；
        - 返回日期列表按最近日期在前。

        【参数说明】
        :param patient: PatientProfile 实例。
        :param start_date: 起始日期（包含）。
        :param end_date: 结束日期（包含）。

        【返回值说明】
        :return: list[date]，按日期倒序排列。

        【异常说明】
        - 起止日期为空或 start_date > end_date：抛出 ValidationError。
        - patient 无效：抛出 ValidationError。
        """
        if not patient or not getattr(patient, "id", None):
            raise ValidationError("患者信息无效。")
        if start_date is None or end_date is None:
            raise ValidationError("起止日期不能为空。")
        if start_date > end_date:
            raise ValidationError("起始日期不能晚于结束日期。")

        start_dt, end_dt = cls._build_date_range(start_date, end_date)

        created_times = QuestionnaireSubmission.objects.filter(
            patient_id=patient.id,
            created_at__gte=start_dt,
            created_at__lte=end_dt,
        ).values_list("created_at", flat=True)

        local_dates: set[date] = set()
        for created_at in created_times:
            local_dt = cls._to_localtime(created_at)
            local_dates.add(local_dt.date())

        return sorted(local_dates, reverse=True)

    @classmethod
    def list_daily_questionnaire_scores(
        cls,
        *,
        patient: "PatientProfile",
        start_date: date,
        end_date: date,
        questionnaire_code: str,
    ) -> list[dict[str, Any]]:
        """
        按日返回指定问卷在时间区间内的得分列表（缺失日期补 0）。

        【功能说明】
        - 在闭区间 [start_date, end_date] 内统计某问卷每天的得分；
        - 同一天多次提交时，取当天最新一条提交的分数；
        - 若当日没有提交，分数返回 0。

        【使用方法】
        - list_daily_questionnaire_scores(
              patient=patient,
              start_date=date(2025, 1, 1),
              end_date=date(2025, 1, 31),
              questionnaire_code=QuestionnaireCode.Q_SLEEP,
          )

        【参数说明】
        - patient: PatientProfile 实例。
        - start_date: date，开始日期（含）。
        - end_date: date，结束日期（含）。
        - questionnaire_code: str，问卷编码，例如 Q_SLEEP。

        【返回值说明】
        - list[dict]，结构示例：
          [
            {"date": date(2025, 1, 1), "score": Decimal("3.00")},
            {"date": date(2025, 1, 2), "score": Decimal("0")},
          ]

        【异常说明】
        - patient 无效或日期非法：抛出 ValidationError。
        - questionnaire_code 无效：抛出 ValidationError。
        """
        if not patient or not getattr(patient, "id", None):
            raise ValidationError("患者信息无效。")
        if start_date is None or end_date is None:
            raise ValidationError("起止日期不能为空。")
        if start_date > end_date:
            raise ValidationError("起始日期不能晚于结束日期。")
        if not questionnaire_code:
            raise ValidationError("问卷编码不能为空。")
        if not Questionnaire.objects.filter(code=questionnaire_code).exists():
            raise ValidationError("问卷编码无效。")

        start_dt, end_dt = cls._build_date_range(start_date, end_date)

        submissions = (
            QuestionnaireSubmission.objects.filter(
                patient_id=patient.id,
                questionnaire__code=questionnaire_code,
                created_at__gte=start_dt,
                created_at__lte=end_dt,
            )
            .only("created_at", "total_score")
            .order_by("-created_at")
        )

        scores_by_date: dict[date, Decimal | None] = {}
        current_date = start_date
        while current_date <= end_date:
            scores_by_date[current_date] = None
            current_date += timedelta(days=1)

        for submission in submissions:
            local_date = cls._to_localtime(submission.created_at).date()
            if local_date in scores_by_date and scores_by_date[local_date] is None:
                scores_by_date[local_date] = submission.total_score or Decimal("0")

        results: list[dict[str, Any]] = []
        for day in sorted(scores_by_date.keys()):
            score = scores_by_date[day]
            results.append({"date": day, "score": score or Decimal("0")})

        return results

    @classmethod
    def list_daily_cough_hemoptysis_flags(
        cls,
        *,
        patient: "PatientProfile",
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        """
        按日返回咳嗽问卷“咯血题”(ID=40)是否为咯血的结果。

        【功能说明】
        - 仅查询问卷类型数据（Q_COUGH），并限定题目 ID=40；
        - 同一天多次提交时，仅取当天最新一条；
        - 选项序号为 3 或 4 视为“咯血”，1 或 2 不算；
        - 若当日无提交或该题未作答，默认返回 False。

        【使用方法】
        - list_daily_cough_hemoptysis_flags(
              patient=patient,
              start_date=date(2025, 1, 1),
              end_date=date(2025, 1, 31),
          )

        【参数说明】
        - patient: PatientProfile 实例。
        - start_date: date，开始日期（含）。
        - end_date: date，结束日期（含）。

        【返回值说明】
        - list[dict]，结构示例：
          [
            {"date": date(2025, 1, 1), "has_hemoptysis": False},
            {"date": date(2025, 1, 2), "has_hemoptysis": True},
          ]

        【异常说明】
        - patient 无效或日期非法：抛出 ValidationError。
        - 咳嗽问卷或题目不存在：抛出 ValidationError。
        """
        if not patient or not getattr(patient, "id", None):
            raise ValidationError("患者信息无效。")
        if start_date is None or end_date is None:
            raise ValidationError("起止日期不能为空。")
        if start_date > end_date:
            raise ValidationError("起始日期不能晚于结束日期。")

        if not Questionnaire.objects.filter(code=QuestionnaireCode.Q_COUGH).exists():
            raise ValidationError("咳嗽问卷不存在。")
        if not QuestionnaireQuestion.objects.filter(
            id=cls.COUGH_BLOOD_QUESTION_ID,
            questionnaire__code=QuestionnaireCode.Q_COUGH,
        ).exists():
            raise ValidationError("咳嗽问卷未配置咯血题目。")

        start_dt, end_dt = cls._build_date_range(start_date, end_date)

        submissions = (
            QuestionnaireSubmission.objects.filter(
                patient_id=patient.id,
                questionnaire__code=QuestionnaireCode.Q_COUGH,
                created_at__gte=start_dt,
                created_at__lte=end_dt,
            )
            .order_by("-created_at")
            .prefetch_related(
                Prefetch(
                    "answers",
                    queryset=QuestionnaireAnswer.objects.filter(
                        question_id=cls.COUGH_BLOOD_QUESTION_ID
                    ).select_related("option"),
                    to_attr="cough_blood_answers",
                )
            )
        )

        results_by_date: dict[date, bool] = {}
        current_date = start_date
        while current_date <= end_date:
            results_by_date[current_date] = False
            current_date += timedelta(days=1)

        processed_dates: set[date] = set()
        for submission in submissions:
            local_date = cls._to_localtime(submission.created_at).date()
            if local_date not in results_by_date or local_date in processed_dates:
                continue
            processed_dates.add(local_date)

            answers = getattr(submission, "cough_blood_answers", [])
            has_hemoptysis = any(
                answer.option
                and answer.option.seq in (3, 4)
                for answer in answers
            )
            results_by_date[local_date] = has_hemoptysis

        results: list[dict[str, Any]] = []
        for day in sorted(results_by_date.keys()):
            results.append(
                {"date": day, "has_hemoptysis": results_by_date[day]}
            )

        return results

    # 以下这个方法生命周期很短。 仅随着问卷对比功能上线而存在，后续可能会被废弃。有点类似 view.
    @classmethod
    def list_daily_questionnaire_summaries(
        cls,
        *,
        patient_id: int,
        target_date: date,
    ) -> list[dict[str, Any]]:
        """
        查询患者在指定日期的问卷提交摘要（按问卷维度聚合）。

        【功能说明】
        - 仅获取目标日期内的问卷提交记录；
        - 同一问卷同一天多次提交时，仅取当天最新一条；
        - 返回当前提交、上次提交（不含当日）以及分数变化信息。

        【参数说明】
        :param patient_id: 患者 ID。
        :param target_date: 目标日期（自然日）。

        【返回值说明】
        :return: list[dict]，按问卷排序返回，示例：
            [
                {
                    "questionnaire_id": 1,
                    "questionnaire_name": "体能与呼吸困难",
                    "submission_id": 123,
                    "submitted_at": datetime(...),
                    "total_score": Decimal("8.00"),
                    "prev_submission_id": 101,
                    "prev_score": Decimal("7.00"),
                    "prev_submitted_at": datetime(...),
                    "score_change": Decimal("1.00"),
                    "change_type": "up",
                    "change_text": "较上次提升1分",
                },
            ]

        【异常说明】
        - patient_id 为空或 target_date 为空：抛出 ValidationError。
        """
        if not patient_id:
            raise ValidationError("患者ID不能为空。")
        if target_date is None:
            raise ValidationError("查询日期不能为空。")

        start_dt, end_dt = cls._build_date_range(target_date, target_date)
        submissions = (
            QuestionnaireSubmission.objects.filter(
                patient_id=patient_id,
                created_at__gte=start_dt,
                created_at__lte=end_dt,
            )
            .select_related("questionnaire")
            .order_by("-created_at")
        )

        latest_by_questionnaire: dict[int, QuestionnaireSubmission] = {}
        for submission in submissions:
            if submission.questionnaire_id not in latest_by_questionnaire:
                latest_by_questionnaire[submission.questionnaire_id] = submission

        sorted_submissions = sorted(
            latest_by_questionnaire.values(),
            key=lambda item: (item.questionnaire.sort_order, item.questionnaire.name),
        )

        summaries: list[dict[str, Any]] = []
        for submission in sorted_submissions:
            prev_submission = (
                QuestionnaireSubmission.objects.filter(
                    patient_id=patient_id,
                    questionnaire_id=submission.questionnaire_id,
                    created_at__lt=start_dt,
                )
                .order_by("-created_at")
                .first()
            )

            change_info = cls._build_change_info(
                submission.total_score,
                prev_submission.total_score if prev_submission else None,
                prefix="较上次",
            )

            summaries.append(
                {
                    "questionnaire_id": submission.questionnaire_id,
                    "questionnaire_name": submission.questionnaire.name,
                    "submission_id": submission.id,
                    "submitted_at": cls._to_localtime(submission.created_at),
                    "total_score": submission.total_score,
                    "prev_submission_id": prev_submission.id if prev_submission else None,
                    "prev_score": prev_submission.total_score if prev_submission else None,
                    "prev_submitted_at": cls._to_localtime(prev_submission.created_at)
                    if prev_submission
                    else None,
                    "score_change": change_info["score_change"],
                    "change_type": change_info["change_type"],
                    "change_text": change_info["change_text"],
                }
            )

        return summaries

    # 以下这个方法生命周期很短。 仅随着问卷对比功能上线而存在，后续可能会被废弃。有点类似 view.
    @classmethod
    def get_questionnaire_comparison(
        cls,
        *,
        submission_id: int,
    ) -> dict[str, Any]:
        """
        获取单份问卷提交与上一份提交的对比详情（含题目级别）。 

        【功能说明】
        - 基于 submission_id 获取当前问卷提交；
        - 找到该问卷在当前日期之前的上一条提交；
        - 生成问卷总分和题目级别的对比数据。

        【参数说明】
        :param submission_id: 当前问卷提交 ID。

        【返回值说明】
        :return: dict，包含问卷摘要与题目对比明细。

        【异常说明】
        - submission_id 为空或不存在：抛出 ValidationError。
        """
        if not submission_id:
            raise ValidationError("提交记录不能为空。")

        try:
            submission = QuestionnaireSubmission.objects.select_related(
                "questionnaire"
            ).get(id=submission_id)
        except QuestionnaireSubmission.DoesNotExist as exc:
            raise ValidationError("提交记录不存在。") from exc

        current_local_date = cls._to_localtime(submission.created_at).date()
        start_dt, _ = cls._build_date_range(current_local_date, current_local_date)

        prev_submission = (
            QuestionnaireSubmission.objects.filter(
                patient_id=submission.patient_id,
                questionnaire_id=submission.questionnaire_id,
                created_at__lt=start_dt,
            )
            .order_by("-created_at")
            .first()
        )

        current_answers = list(
            QuestionnaireAnswer.objects.filter(submission=submission).select_related(
                "question", "option"
            )
        )
        prev_answers: list[QuestionnaireAnswer] = []
        if prev_submission:
            prev_answers = list(
                QuestionnaireAnswer.objects.filter(
                    submission=prev_submission
                ).select_related("question", "option")
            )

        answers_by_question = cls._group_answers(current_answers)
        prev_answers_by_question = cls._group_answers(prev_answers)

        questions = QuestionnaireQuestion.objects.filter(
            questionnaire=submission.questionnaire
        ).order_by("seq", "id")

        question_details: list[dict[str, Any]] = []
        for question in questions:
            current_items = answers_by_question.get(question.id, [])
            prev_items = prev_answers_by_question.get(question.id, [])

            current_score = cls._sum_answer_score(current_items) if current_items else None
            prev_score = cls._sum_answer_score(prev_items) if prev_items else None

            change_info = cls._build_change_info(
                current_score,
                prev_score,
                prefix="",
            )

            question_details.append(
                {
                    "question_id": question.id,
                    "question_text": question.text,
                    "current_answer": cls._render_answers(current_items),
                    "prev_answer": cls._render_answers(prev_items),
                    "current_score": current_score,
                    "prev_score": prev_score,
                    "score_change": change_info["score_change"],
                    "change_type": change_info["change_type"],
                    "change_text": change_info["change_text"],
                }
            )

        summary_change = cls._build_change_info(
            submission.total_score,
            prev_submission.total_score if prev_submission else None,
            prefix="较上次",
        )
        prev_submitted_at = (
            cls._to_localtime(prev_submission.created_at) if prev_submission else None
        )

        return {
            "questionnaire_id": submission.questionnaire_id,
            "questionnaire_name": submission.questionnaire.name,
            "submission_id": submission.id,
            "submitted_at": cls._to_localtime(submission.created_at),
            "current_score": submission.total_score,
            "prev_submission_id": prev_submission.id if prev_submission else None,
            "prev_score": prev_submission.total_score if prev_submission else None,
            "prev_submitted_at": prev_submitted_at,
            "prev_date": prev_submitted_at.date() if prev_submitted_at else None,
            "score_change": summary_change["score_change"],
            "change_type": summary_change["change_type"],
            "change_text": summary_change["change_text"],
            "questions": question_details,
        }

    @classmethod
    def get_submission_detail_for_patient(
        cls,
        *,
        submission_id: int,
        patient_id: int,
    ) -> dict[str, Any] | None:
        """
        按提交记录 ID 获取指定患者的问卷答题详情。

        【功能说明】
        - 仅返回 submission_id 与 patient_id 同时匹配的问卷提交；
        - 按问卷题目顺序返回每题及本次选择的答案（支持单选/多选）；
        - 若提交不存在或不属于该患者，返回 None。

        【参数说明】
        :param submission_id: 问卷提交 ID。
        :param patient_id: 患者 ID。

        【返回值说明】
        :return: dict | None，示例：
            {
                "submission_id": 1,
                "questionnaire_id": 2,
                "questionnaire_name": "焦虑评估",
                "submitted_at": datetime(...),
                "questions": [
                    {
                        "question_id": 10,
                        "question_text": "最近是否感到紧张？",
                        "q_type": "SINGLE",
                        "answers": ["经常"],
                    },
                    {
                        "question_id": 11,
                        "question_text": "出现了哪些症状？",
                        "q_type": "MULTIPLE",
                        "answers": ["心慌", "手抖"],
                    },
                ],
            }
        """
        if not submission_id or not patient_id:
            return None

        submission = (
            QuestionnaireSubmission.objects.select_related("questionnaire")
            .filter(id=submission_id, patient_id=patient_id)
            .first()
        )
        if not submission:
            return None

        answers = list(
            QuestionnaireAnswer.objects.filter(submission_id=submission.id)
            .select_related("question", "option")
            .order_by("question__seq", "question_id", "option__seq", "id")
        )
        answers_by_question = cls._group_answers(answers)

        questions = QuestionnaireQuestion.objects.filter(
            questionnaire_id=submission.questionnaire_id
        ).order_by("seq", "id")

        question_items: list[dict[str, Any]] = []
        for question in questions:
            selected_answers = answers_by_question.get(question.id, [])

            answer_texts: list[str] = []
            for answer in selected_answers:
                if answer.option and answer.option.text:
                    answer_texts.append(answer.option.text)
                if answer.value_text:
                    answer_texts.append(answer.value_text)

            # 去重并保持顺序，避免极端脏数据导致重复展示
            deduped_answers: list[str] = []
            seen_texts: set[str] = set()
            for text in answer_texts:
                if text in seen_texts:
                    continue
                seen_texts.add(text)
                deduped_answers.append(text)

            question_items.append(
                {
                    "question_id": question.id,
                    "question_text": question.text,
                    "q_type": question.q_type,
                    "answers": deduped_answers,
                }
            )

        score_label = "问卷评分"
        health_state = None
        if is_eq5d5l_code(submission.questionnaire.code):
            score_label = "健康效用指数"
            try:
                health_state = cls._get_eq5d5l_grade_result(
                    submission
                ).details.get("health_state")
            except ValidationError:
                # 历史答卷可能不满足当前五维结构；详情仍应允许查看原始答案。
                health_state = None
        elif is_eqvas_code(submission.questionnaire.code):
            score_label = "EQ-VAS评分"

        return {
            "submission_id": submission.id,
            "questionnaire_id": submission.questionnaire_id,
            "questionnaire_name": submission.questionnaire.name,
            "submitted_at": cls._to_localtime(submission.created_at),
            "score_label": score_label,
            "score_value": submission.total_score,
            "health_state": health_state,
            "questions": question_items,
        }

    @classmethod
    def get_submission_grade_result(
        cls,
        submission_id: int,
    ) -> QuestionnaireGradeResult:
        """返回问卷分级及预警所需的可审计上下文。"""
        if not submission_id:
            raise ValidationError("提交记录不能为空。")

        try:
            submission = QuestionnaireSubmission.objects.select_related(
                "questionnaire"
            ).get(id=submission_id)
        except QuestionnaireSubmission.DoesNotExist as exc:
            raise ValidationError("提交记录不存在。") from exc

        questionnaire_code = submission.questionnaire.code
        if is_eq5d5l_code(questionnaire_code):
            return cls._get_eq5d5l_grade_result(submission)
        if is_eqvas_code(questionnaire_code):
            return cls._get_eqvas_grade_result(submission)

        return QuestionnaireGradeResult(
            grade_level=cls._get_legacy_submission_grade(submission),
            rule_version="LEGACY_FIXED_CODE_V1",
            score_label="总分",
        )

    @classmethod
    def get_submission_grade(cls, submission_id: int) -> int | None:
        """兼容返回问卷分级；不可分级的有效空值返回None。"""
        return cls.get_submission_grade_result(submission_id).grade_level

    @classmethod
    def _get_eq5d5l_grade_result(
        cls,
        submission: QuestionnaireSubmission,
    ) -> QuestionnaireGradeResult:
        levels = cls._get_eq5d5l_submission_levels(submission)
        grade_level = Eq5d5lChinaCalculator.grade(levels)
        max_dimension_level = max(levels)
        max_dimensions = [
            name
            for name, level in zip(
                Eq5d5lChinaCalculator.DIMENSION_NAMES,
                levels,
            )
            if level == max_dimension_level
        ]
        utility_index = submission.total_score
        if utility_index is None:
            utility_index = Eq5d5lChinaCalculator.calculate(levels)

        return QuestionnaireGradeResult(
            grade_level=grade_level,
            rule_version="EQ5D5L_MAX_DIMENSION_V1",
            score_label="健康效用指数",
            details={
                "health_state": "".join(str(level) for level in levels),
                "utility_index": cls._format_decimal(utility_index),
                "max_dimension_level": max_dimension_level,
                "max_dimensions": max_dimensions,
            },
        )

    @classmethod
    def _get_eqvas_grade_result(
        cls,
        submission: QuestionnaireSubmission,
    ) -> QuestionnaireGradeResult:
        questions = list(
            QuestionnaireQuestion.objects.filter(
                questionnaire_id=submission.questionnaire_id,
            )
            .only("id", "q_type", "seq")
            .order_by("seq", "id")
        )
        if len(questions) != cls.EQVAS_QUESTION_COUNT:
            raise ValidationError("EQ-VAS 问卷必须恰好配置一道题。")
        question = questions[0]
        if question.q_type != QuestionType.TEXT:
            raise ValidationError("EQ-VAS 问卷题目必须为问答/填空题。")

        answers = list(
            QuestionnaireAnswer.objects.filter(
                submission=submission,
                question_id=question.id,
            )
            .only("id", "option_id", "value_text")
            .order_by("id")
        )
        if len(answers) > 1 or any(answer.option_id for answer in answers):
            raise ValidationError("EQ-VAS 问卷答案结构错误。")

        value_text = answers[0].value_text if answers else None
        grade_level = EqVasCalculator.grade(value_text)
        details: dict[str, Any] = {}
        if grade_level is not None:
            details["vas_score"] = int(value_text)

        return QuestionnaireGradeResult(
            grade_level=grade_level,
            rule_version="EQVAS_ABSOLUTE_A_V1",
            score_label="EQ-VAS评分",
            details=details,
        )

    @classmethod
    def _get_eq5d5l_submission_levels(
        cls,
        submission: QuestionnaireSubmission,
    ) -> tuple[int, ...]:
        questions = list(
            QuestionnaireQuestion.objects.filter(
                questionnaire_id=submission.questionnaire_id,
            )
            .only("id", "q_type", "seq")
            .order_by("seq", "id")
        )
        if len(questions) != cls.EQ5D5L_QUESTION_COUNT:
            raise ValidationError("EQ-5D-5L 问卷必须恰好配置五道题。")
        if any(question.q_type != QuestionType.SINGLE for question in questions):
            raise ValidationError("EQ-5D-5L 五个健康维度必须均为单选题。")

        answers_by_question: dict[int, list[QuestionnaireAnswer]] = {}
        answers = QuestionnaireAnswer.objects.filter(
            submission=submission,
        ).select_related("option")
        for answer in answers:
            answers_by_question.setdefault(answer.question_id, []).append(answer)

        levels: list[int] = []
        for question in questions:
            question_answers = answers_by_question.get(question.id, [])
            if (
                len(question_answers) != 1
                or not question_answers[0].option
                or question_answers[0].option.question_id != question.id
            ):
                raise ValidationError(
                    "EQ-5D-5L 五个健康维度必须各选择一个选项。"
                )
            option_value = question_answers[0].option.value
            if option_value not in {"1", "2", "3", "4", "5"}:
                raise ValidationError(
                    "EQ-5D-5L 健康维度选项值必须为 1 至 5 的整数。"
                )
            levels.append(int(option_value))
        return tuple(levels)

    @classmethod
    def _get_legacy_submission_grade(
        cls,
        submission: QuestionnaireSubmission,
    ) -> int:
        questionnaire_code = submission.questionnaire.code
        total_score = submission.total_score
        if total_score is None:
            answers = list(
                QuestionnaireAnswer.objects.filter(
                    submission=submission
                ).select_related("option")
            )
            total_score = cls._sum_answer_score(answers)

        if questionnaire_code in (
            QuestionnaireCode.Q_PHYSICAL,
            QuestionnaireCode.Q_BREATH,
        ):
            if total_score <= 1:
                grade_level = 1
            elif total_score == 2:
                grade_level = 2
            elif total_score == 3:
                grade_level = 3
            elif total_score == 4:
                grade_level = 4
            else:
                raise ValidationError("问卷分数不在有效范围内。")
        elif questionnaire_code == QuestionnaireCode.Q_COUGH:
            bleeding_score = Decimal("0.00")
            bleeding_answers = QuestionnaireAnswer.objects.filter(
                submission=submission,
                question_id=cls.COUGH_BLOOD_QUESTION_ID,
            ).select_related("option")
            for answer in bleeding_answers:
                if not answer.option:
                    continue
                if answer.option.score > bleeding_score:
                    bleeding_score = answer.option.score

            if bleeding_score >= Decimal("9") or total_score >= Decimal("9"):
                grade_level = 4
            elif total_score >= Decimal("6"):
                grade_level = 3
            elif total_score >= Decimal("3"):
                grade_level = 2
            elif total_score >= Decimal("0"):
                grade_level = 1
            else:
                raise ValidationError("问卷分数不在有效范围内。")
        elif questionnaire_code == QuestionnaireCode.Q_APPETITE:
            if total_score >= Decimal("14"):
                grade_level = 4
            elif total_score >= Decimal("9"):
                grade_level = 3
            elif total_score >= Decimal("4"):
                grade_level = 2
            elif total_score >= Decimal("0"):
                grade_level = 1
            else:
                raise ValidationError("问卷分数不在有效范围内。")
        elif questionnaire_code == QuestionnaireCode.Q_PAIN:
            pain_answers = QuestionnaireAnswer.objects.filter(
                submission=submission
            ).select_related("option")
            pain_sites_with_max = set()
            for answer in pain_answers:
                if not answer.option:
                    continue
                if answer.option.score == Decimal("9"):
                    pain_sites_with_max.add(answer.question_id)

            max_score_sites = len(pain_sites_with_max)

            if max_score_sites >= 3:
                grade_level = 4
            elif total_score > Decimal("20") and max_score_sites >= 1:
                grade_level = 3
            elif total_score > Decimal("10") and max_score_sites == 0:
                grade_level = 2
            elif total_score <= Decimal("4"):
                grade_level = 1
            elif total_score <= Decimal("8"):
                grade_level = 2
            elif total_score <= Decimal("20"):
                grade_level = 3
            elif total_score <= Decimal("36"):
                grade_level = 4
            else:
                raise ValidationError("问卷分数不在有效范围内。")
        elif questionnaire_code == QuestionnaireCode.Q_SLEEP:
            raw_score = int(total_score)
            t_score = cls.SLEEP_T_SCORE_MAP.get(raw_score)
            if t_score is None:
                raise ValidationError("睡眠评估原始分数不在有效范围内。")

            if t_score <= Decimal("55"):
                grade_level = 1
            elif t_score < Decimal("60"):
                grade_level = 2
            elif t_score < Decimal("70"):
                grade_level = 3
            else:
                grade_level = 4
        elif questionnaire_code == QuestionnaireCode.Q_DEPRESSIVE:
            if total_score >= Decimal("15"):
                grade_level = 4
            elif total_score >= Decimal("10"):
                grade_level = 3
            elif total_score >= Decimal("5"):
                grade_level = 2
            elif total_score >= Decimal("0"):
                grade_level = 1
            else:
                raise ValidationError("问卷分数不在有效范围内。")
        elif questionnaire_code == QuestionnaireCode.Q_ANXIETY:
            if total_score >= Decimal("15"):
                grade_level = 4
            elif total_score >= Decimal("10"):
                grade_level = 3
            elif total_score >= Decimal("5"):
                grade_level = 2
            elif total_score >= Decimal("0"):
                grade_level = 1
            else:
                raise ValidationError("问卷分数不在有效范围内。")
        elif questionnaire_code == QuestionnaireCode.Q_KQNMLB:
            if total_score >= Decimal("10"):
                grade_level = 4
            elif total_score >= Decimal("5"):
                grade_level = 3
            elif total_score >= Decimal("1"):
                grade_level = 2
            elif total_score == Decimal("0"):
                grade_level = 1
            else:
                raise ValidationError("问卷分数不在有效范围内。")
        else:
            raise ValidationError("该问卷暂不支持分级。")

        return grade_level

    @staticmethod
    def _build_date_range(start_date: date, end_date: date) -> tuple[datetime, datetime]:
        start_dt = datetime.combine(start_date, datetime.min.time())
        end_dt = datetime.combine(end_date, datetime.max.time())

        if timezone.is_aware(timezone.now()):
            start_dt = timezone.make_aware(start_dt)
            end_dt = timezone.make_aware(end_dt)

        return start_dt, end_dt

    @staticmethod
    def _to_localtime(dt: datetime) -> datetime:
        if timezone.is_aware(dt):
            return timezone.localtime(dt)
        return dt

    @staticmethod
    def _group_answers(
        answers: list[QuestionnaireAnswer],
    ) -> dict[int, list[QuestionnaireAnswer]]:
        grouped: dict[int, list[QuestionnaireAnswer]] = {}
        for answer in answers:
            grouped.setdefault(answer.question_id, []).append(answer)
        return grouped

    @staticmethod
    def _render_answers(answers: list[QuestionnaireAnswer]) -> str | None:
        if not answers:
            return None

        texts: list[str] = []
        for answer in answers:
            if answer.option and answer.option.text:
                texts.append(answer.option.text)
            if answer.value_text:
                texts.append(answer.value_text)

        if not texts:
            return None

        return "、".join(texts)

    @staticmethod
    def _sum_answer_score(answers: list[QuestionnaireAnswer]) -> Decimal:
        total = Decimal("0.00")
        for answer in answers:
            if answer.option:
                total += answer.option.score
        return total

    @staticmethod
    def _format_decimal(value: Decimal) -> str:
        text = format(value.quantize(Decimal("0.01")), "f")
        return text.rstrip("0").rstrip(".")

    @classmethod
    def _build_change_info(
        cls,
        current_score: Decimal | None,
        prev_score: Decimal | None,
        *,
        prefix: str,
    ) -> dict[str, Any]:
        if current_score is None or prev_score is None:
            return {
                "score_change": None,
                "change_type": "none",
                "change_text": "无上次记录",
            }

        diff = current_score - prev_score
        if diff == 0:
            return {
                "score_change": Decimal("0.00"),
                "change_type": "neutral",
                "change_text": "持平",
            }

        label = "提升" if diff > 0 else "下降"
        change_value = cls._format_decimal(abs(diff))
        prefix_text = f"{prefix}" if prefix else ""
        return {
            "score_change": diff,
            "change_type": "up" if diff > 0 else "down",
            "change_text": f"{prefix_text}{label}{change_value}分",
        }
