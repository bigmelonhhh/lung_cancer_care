"""问卷提交业务逻辑服务。"""

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.models import Questionnaire, QuestionnaireOption, QuestionnaireQuestion
from core.service import tasks as task_service
from health_data.models import QuestionnaireAnswer, QuestionnaireSubmission
from health_data.services.health_metric import HealthMetricService

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from users.models import PatientProfile


class QuestionnaireSubmissionService:
    """处理问卷提交、算分及指标落库。"""
    COUGH_BLOOD_QUESTION_ID = 40
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
        提交问卷答案（仅选择题），并完成完整性校验、总分计算及（可选）指标落库。

        【功能说明】
        - 根据传入的问卷编码和选项答案，完成一次问卷提交；
        - 校验所有题目是否都已作答，否则抛出 ValidationError；
        - 在当前仅支持选择题场景下，对所有选中选项的 score 做简单累加，得到 total_score；
        - 将答题明细保存到 QuestionnaireAnswer，将总分冗余到 QuestionnaireSubmission.total_score；
        - 提交成功后写入一条 HealthMetric 记录（metric_type 使用问卷 code）。
        - 提交成功后同步更新患者当天的问卷任务状态。

        【参数说明】
        :param patient_id: 患者ID（users.PatientProfile 的主键）
        :param questionnaire_id: 问卷ID，对应 core.Questionnaire.id
        :param answers_data: 答案列表，目前仅支持选择题，格式示例：
               [
                   {"option_id": 10},
                   {"option_id": 12},
                   {"option_id": 13}
               ]
               - 多选题：同一题目会传多条记录（不同 option_id）；
               - 预留字段：将来如需文本补充，可在 item 中增加 "value_text"。
        :param task_id: 关联的任务ID (可选)，用于与任务系统打通（例如随访任务），不传则为空。

        【返回值说明】
        :return: 创建好的 QuestionnaireSubmission 实例，包含：
                 - patient/questionnaire/task 等基础信息；
                 - total_score：本次提交的总得分（按问卷计分策略计算，当前为简单累加）。
                 具体答题明细可通过 submission.answers 反向查询 QuestionnaireAnswer。

        【异常说明】
        - 若当前问卷未配置任何题目：抛出 ValidationError("当前问卷未配置题目。")
        - 若 answers_data 为空：抛出 ValidationError("答案列表不能为空。")
        - 若某个答案项缺少 option_id：抛出 ValidationError("答案项缺少 option_id。")
        - 若存在无效的 option_id：抛出 ValidationError("存在无效的选项，请检查填写内容。")
        - 若答案中包含不属于该问卷的选项：
              ValidationError("答案中包含不属于该问卷的选项。")
        - 若用户未答完所有题目：
              ValidationError("问卷未全部作答，请完成所有题目后再提交。")

        【使用示例】
        >>> from health_data.services.questionnaire_submission import QuestionnaireSubmissionService
        >>> submission = QuestionnaireSubmissionService.submit_questionnaire(
        ...     patient_id=1,
        ...     questionnaire_id=1,
        ...     answers_data=[
        ...         {"option_id": 10},
        ...         {"option_id": 12},
        ...         {"option_id": 13},
        ...     ],
        ...     task_id=12345,
        ... )
        >>> submission.total_score
        Decimal('21.00')
        >>> list(submission.answers.all())  # doctest: +ELLIPSIS
        [...]
        """
        # 1. 获取问卷模板
        questionnaire = Questionnaire.objects.get(id=questionnaire_id)

        # 1.1 加载该问卷下的所有题目，用于“是否全部作答”的校验
        questions = list(
            QuestionnaireQuestion.objects.filter(questionnaire=questionnaire).only("id")
        )
        if not questions:
            raise ValidationError("当前问卷未配置题目。")

        # 1.2 从答案中收集所有 option_id，并做基础校验
        if not answers_data:
            raise ValidationError("答案列表不能为空。")

        option_ids: list[int] = []
        for item in answers_data:
            opt_id = item.get("option_id")
            if not opt_id:
                raise ValidationError("答案项缺少 option_id。")
            option_ids.append(opt_id)

        # 1.3 预加载所有选项，并校验：
        #   - 选项是否存在
        #   - 选项是否属于当前问卷
        options_qs = (
            QuestionnaireOption.objects.select_related("question")
            .filter(id__in=option_ids)
        )
        options_map = {opt.id: opt for opt in options_qs}

        if len(options_map) != len(set(option_ids)):
            missing_ids = {oid for oid in option_ids if oid not in options_map}
            if missing_ids:
                raise ValidationError("存在无效的选项，请检查填写内容。")

        # 校验选项是否都属于当前问卷，并按题目分组
        answers_by_question: dict[int, list[QuestionnaireOption]] = {}
        for opt_id in option_ids:
            option = options_map[opt_id]
            if option.question.questionnaire_id != questionnaire.id:
                raise ValidationError("答案中包含不属于该问卷的选项。")
            q_id = option.question_id
            answers_by_question.setdefault(q_id, []).append(option)

        # 1.4 校验是否所有题目都已作答（业务要求：必须答完所有题目）
        question_ids = {q.id for q in questions}
        answered_question_ids = set(answers_by_question.keys())
        missing_question_ids = question_ids - answered_question_ids
        if missing_question_ids:
            raise ValidationError("问卷未全部作答，请完成所有题目后再提交。")

        # 2. 创建提交记录
        submission = QuestionnaireSubmission.objects.create(
            patient_id=patient_id,
            questionnaire=questionnaire,
            task_id=task_id,
        )

        # 3. 保存答案明细并计算总分
        total_score = Decimal("0.00")

        answers_to_create = []
        for item in answers_data:
            opt_id = item.get("option_id")
            option = options_map[opt_id]  # 前面已校验存在

            answer = QuestionnaireAnswer(
                submission=submission,
                question=option.question,
                option=option,
                value_text=item.get("value_text"),
            )

            # 简单累加策略：直接加选项分
            if questionnaire.calculation_strategy == "SUM":
                total_score += option.score

            answers_to_create.append(answer)

        QuestionnaireAnswer.objects.bulk_create(answers_to_create)

        # 4. 更新总分
        
        submission.total_score = total_score
        submission.save(update_fields=["total_score"])
        task_service.complete_daily_questionnaire_tasks(
            patient_id=patient_id,
            occurred_at=submission.created_at,
        )

        # 5. 将问卷总分落库到 HealthMetric：
        #    - metric_type 使用问卷的 code，例如 Q_SLEEP、Q_PAIN 等；
        #    - value_main 存放本次问卷总分；
        #    - source 固定为手动录入；
        #    - questionnaire_submission 关联当前提交记录，便于后续串联查询。
        try:
            HealthMetricService.save_manual_metric(
                patient_id=patient_id,
                metric_type=questionnaire.code,
                measured_at=submission.created_at,
                value_main=total_score,
                questionnaire_submission_id=submission.id,
            )
        except Exception:
            logger.exception(
                "问卷 %s 提交成功，但同步 HealthMetric 失败。submission_id=%s",
                questionnaire.name,
                submission.id,
            )

        return submission

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
            created_at__lt=end_dt,
        ).values_list("created_at", flat=True)

        local_dates: set[date] = set()
        for created_at in created_times:
            local_dt = cls._to_localtime(created_at)
            local_dates.add(local_dt.date())

        return sorted(local_dates, reverse=True)

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
                created_at__lt=end_dt,
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
    def get_submission_grade(cls, submission_id: int) -> int:
        """
        根据问卷类型计算当前提交的分级结果。

        【功能说明】
        - 根据问卷 code 选择不同的分级规则；
        - 当前支持体能评估（Q_PHYSICAL）、呼吸评估（Q_BREATH）与咳嗽评估（Q_COUGH）。

        【参数说明】
        :param submission_id: 问卷提交 ID。

        【返回值说明】
        :return: int，分级数字（1-4）。
        """
        if not submission_id:
            raise ValidationError("提交记录不能为空。")

        try:
            submission = QuestionnaireSubmission.objects.select_related(
                "questionnaire"
            ).get(id=submission_id)
        except QuestionnaireSubmission.DoesNotExist as exc:
            raise ValidationError("提交记录不存在。") from exc

        questionnaire_code = submission.questionnaire.code
        total_score = submission.total_score
        if total_score is None:
            answers = list(
                QuestionnaireAnswer.objects.filter(
                    submission=submission
                ).select_related("option")
            )
            total_score = cls._sum_answer_score(answers)

        if questionnaire_code in ("Q_PHYSICAL", "Q_BREATH"):
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
        elif questionnaire_code == "Q_COUGH":
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
        elif questionnaire_code == "Q_APPETITE":
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
        elif questionnaire_code == "Q_PAIN":
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
        elif questionnaire_code == "Q_SLEEP":
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
        elif questionnaire_code == "Q_DEPRESSIVE":
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
        elif questionnaire_code == "Q_ANXIETY":
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
        else:
            raise ValidationError("该问卷暂不支持分级。")

        return grade_level

    @staticmethod
    def _build_date_range(start_date: date, end_date: date) -> tuple[datetime, datetime]:
        query_end_date = end_date + timedelta(days=1)
        start_dt = datetime.combine(start_date, datetime.min.time())
        end_dt = datetime.combine(query_end_date, datetime.min.time())

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
