"""问卷提交业务逻辑服务。"""

import logging
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.models import Questionnaire, QuestionnaireOption, QuestionnaireQuestion
from health_data.models import QuestionnaireAnswer, QuestionnaireSubmission
from health_data.services.health_metric import HealthMetricService

logger = logging.getLogger(__name__)


class QuestionnaireSubmissionService:
    """处理问卷提交、算分及指标落库。"""

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
        - 若问卷配置了 metric_type，则同时写入一条 HealthMetric 记录。

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
