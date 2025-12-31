"""随访问卷计划库相关业务服务。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from django.db.models import Prefetch

from core.models import Questionnaire, QuestionnaireOption, QuestionnaireQuestion


class QuestionnaireService:
    """问卷业务服务封装。"""

    @staticmethod
    def get_active_questionnaires() -> List[Questionnaire]:
        """
        【功能说明】
        - 查询所有启用中的问卷模板（is_active=True）；
        - 按 sort_order、name 排序；
        - 直接返回 Model 对象列表，供上层业务使用。

        【返回参数说明】
        - 返回 List[Questionnaire]。

        【使用示例】
        >>> from core.service.questionnaire import QuestionnaireService
        >>> qs = QuestionnaireService.get_active_questionnaires()
        >>> for q in qs:
        ...     print(q.name, q.code)
        """
        return list(
            Questionnaire.objects.filter(is_active=True).order_by("sort_order", "name")
        )

    @staticmethod
    def get_questionnaire_detail(questionnaire_id: int) -> Optional[Dict[str, Any]]:
        """
        【功能说明】
        - 获取单个问卷的完整详情（包含题目与选项）。
        - 内部复用 get_questionnaires_details 以利用其预加载逻辑。

        【参数说明】
        - questionnaire_id: 问卷 ID。

        【返回参数说明】
        - 返回问卷详情字典；若 ID 不存在则返回 None。
        """
        details = QuestionnaireService.get_questionnaires_details([questionnaire_id])
        return details[0] if details else None

    @staticmethod
    def get_questionnaires_details(
        questionnaire_ids: List[int],
    ) -> List[Dict[str, Any]]:
        """
        【功能说明】
        - 批量获取问卷详情（包含题目与选项）。
        - 使用 prefetch_related 预加载题目和选项，避免 N+1 查询问题。
        - 结果列表严格按照传入的 questionnaire_ids 顺序排列。

        【参数说明】
        - questionnaire_ids: 问卷 ID 列表。

        【返回参数说明】
        - 返回字典列表，结构如下：
          [
            {'id': 1,
            'name': '睡眠质量评估 (PROMIS-SD 简版)',
            'code': 'Q_SLEEP',
            'questions': [{'id': 1,
            'text': '您最近的睡眠质量是...',
            'q_type': 'SINGLE',
            'is_required': True,
            'section': '',
            'options': [{'id': 1, 'text': '非常差', 'value': 5, 'score': 5},
                {'id': 2, 'text': '差', 'value': 4, 'score': 4},
                {'id': 3, 'text': '一般', 'value': 3, 'score': 3},
                {'id': 4, 'text': '好', 'value': 2, 'score': 2},
                {'id': 5, 'text': '非常好', 'value': 1, 'score': 1}]},
            {'id': 2,
            'text': '睡眠令人恢复精神。',
            'q_type': 'SINGLE',
            'is_required': True,
            'section': '',
            'options': [{'id': 6, 'text': '完全没有', 'value': 5, 'score': 5},
                {'id': 7, 'text': '一点点', 'value': 4, 'score': 4},
                {'id': 8, 'text': '有些', 'value': 3, 'score': 3},
                {'id': 9, 'text': '相当多', 'value': 2, 'score': 2},
                {'id': 10, 'text': '非常', 'value': 1, 'score': 1}]},
          ]
        """
        if not questionnaire_ids:
            return []

        # 1. 构造预加载查询集，确保题目和选项按 seq 排序
        # 选项预加载：按 seq 排序
        options_qs = QuestionnaireOption.objects.order_by("seq")

        # 题目预加载：按 seq 排序，并嵌套预加载选项
        questions_qs = QuestionnaireQuestion.objects.order_by("seq").prefetch_related(
            Prefetch("options", queryset=options_qs)
        )

        # 2. 主查询：获取问卷并预加载题目
        qs = Questionnaire.objects.filter(id__in=questionnaire_ids).prefetch_related(
            Prefetch("questions", queryset=questions_qs)
        )

        # 3. 建立 ID -> 对象映射，以便按输入顺序重组
        q_map = {q.id: q for q in qs}

        results = []
        for q_id in questionnaire_ids:
            q = q_map.get(q_id)
            if not q:
                continue

            # 序列化题目与选项
            questions_data = []
            for question in q.questions.all():
                options_data = [
                    {
                        "id": opt.id,
                        "text": opt.text,
                        "value": opt.value,
                        "score": int(opt.score),
                    }
                    for opt in question.options.all()
                ]

                questions_data.append(
                    {
                        "id": question.id,
                        "text": question.text,
                        "q_type": question.q_type,
                        "is_required": question.is_required,
                        "section": question.section,
                        "options": options_data,
                    }
                )

            results.append(
                {
                    "id": q.id,
                    "name": q.name,
                    "code": q.code,
                    "questions": questions_data,
                }
            )

        return results

    @classmethod
    def print_all_questionnaire_contents(cls) -> None:
        """
        按顺序打印所有问卷、题目与选项内容，便于人工核对。

        【功能说明】
        - 问卷按 sort_order、name 排序；
        - 题目按 seq 排序；
        - 选项按 seq 排序；
        - 直接打印到控制台，适合在 Django shell 中使用。

        【使用示例】
        >>> from core.service.questionnaire import QuestionnaireService
        >>> QuestionnaireService.print_all_questionnaire_contents()
        """
        options_qs = QuestionnaireOption.objects.order_by("seq", "id")
        questions_qs = QuestionnaireQuestion.objects.order_by(
            "seq", "id"
        ).prefetch_related(Prefetch("options", queryset=options_qs))
        questionnaires = (
            Questionnaire.objects.all()
            .order_by("sort_order", "name", "id")
            .prefetch_related(Prefetch("questions", queryset=questions_qs))
        )

        lines: List[str] = []
        questionnaire_count = 0
        question_count = 0
        option_count = 0

        for questionnaire in questionnaires:
            questionnaire_count += 1
            lines.append(
                "[Questionnaire] "
                f"id={questionnaire.id} | sort={questionnaire.sort_order} | "
                f"active={questionnaire.is_active} | code={questionnaire.code} | "
                f"name={questionnaire.name}"
            )
            for question in questionnaire.questions.all():
                question_count += 1
                lines.append(
                    "  [Question] "
                    f"id={question.id} | seq={question.seq} | "
                    f"required={question.is_required} | type={question.q_type} | "
                    f"weight={question.weight} | "
                    f"section={question.section or '-'} | text={question.text}"
                )
                for option in question.options.all():
                    option_count += 1
                    lines.append(
                        "    "
                        "[Option] "
                        f"id={option.id} | seq={option.seq} | "
                        f"text={option.text} | value={option.value or '-'} | "
                        f"score={option.score}"
                    )
            lines.append("")

        lines.insert(
            0,
            f"TOTAL questionnaires={questionnaire_count}, "
            f"questions={question_count}, options={option_count}",
        )
        lines.insert(1, "")

        for line in lines:
            print(line)
