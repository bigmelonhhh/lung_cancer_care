from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from core.models import (
    DailyTask,
    Questionnaire,
    QuestionnaireOption,
    QuestionnaireQuestion,
    choices,
)
from core.models.choices import QuestionType
from health_data.models import (
    HealthMetric,
    QuestionnaireAnswer,
    QuestionnaireSubmission,
)
from health_data.services.questionnaire_submission import QuestionnaireSubmissionService
from users.models import PatientProfile


class Eq5d5lQuestionnaireSubmissionTests(TestCase):
    def setUp(self):
        self.patient = PatientProfile.objects.create(
            phone="13800008888",
            name="EQ-5D-5L测试患者",
        )
        self.questionnaire = Questionnaire.objects.create(
            name="EQ5D5L量表",
            code="Q_EQ5D5L",
            calculation_strategy="SUM",
        )
        self.dimension_questions = []
        self.dimension_options = []
        dimension_names = ("行动能力", "自我照顾", "日常活动", "疼痛/不适", "焦虑/抑郁")
        for seq, name in enumerate(dimension_names):
            question = QuestionnaireQuestion.objects.create(
                questionnaire=self.questionnaire,
                text=name,
                q_type=QuestionType.SINGLE,
                is_required=True,
                seq=seq,
            )
            options = []
            for level in range(1, 6):
                options.append(
                    QuestionnaireOption.objects.create(
                        question=question,
                        text=f"{level}级",
                        value=str(level),
                        score=Decimal("99"),
                        seq=level,
                    )
                )
            self.dimension_questions.append(question)
            self.dimension_options.append(options)

    def _answers(self, levels=(2, 1, 3, 2, 4)):
        return [
            {"option_id": options[level - 1].id}
            for options, level in zip(self.dimension_options, levels)
        ]

    def test_submit_eq5d5l_uses_option_values_for_health_utility_index(self):
        submission = QuestionnaireSubmissionService.submit_questionnaire(
            patient_id=self.patient.id,
            questionnaire_id=self.questionnaire.id,
            answers_data=self._answers(),
        )

        self.assertEqual(submission.total_score, Decimal("0.55"))
        self.assertEqual(submission.answers.count(), 5)
        self.assertEqual(
            HealthMetric.objects.get(
                questionnaire_submission=submission
            ).value_main,
            Decimal("0.55"),
        )

    def test_eq5d5l_requires_all_dimensions_even_if_admin_marks_one_optional(self):
        self.dimension_questions[-1].is_required = False
        self.dimension_questions[-1].save(update_fields=["is_required"])

        with self.assertRaisesMessage(
            ValidationError,
            "EQ-5D-5L 五个健康维度必须各选择一个选项",
        ):
            QuestionnaireSubmissionService.submit_questionnaire(
                patient_id=self.patient.id,
                questionnaire_id=self.questionnaire.id,
                answers_data=self._answers()[:-1],
            )

        self.assertEqual(QuestionnaireSubmission.objects.count(), 0)

    def test_eq5d5l_requires_exact_five_single_question_structure(self):
        QuestionnaireQuestion.objects.create(
            questionnaire=self.questionnaire,
            text="多余题目",
            q_type=QuestionType.TEXT,
            is_required=False,
            seq=5,
        )

        with self.assertRaisesMessage(
            ValidationError,
            "EQ-5D-5L 问卷必须恰好配置五道题",
        ):
            QuestionnaireSubmissionService.submit_questionnaire(
                patient_id=self.patient.id,
                questionnaire_id=self.questionnaire.id,
                answers_data=self._answers(),
            )

    def test_eq5d5l_rejects_non_single_dimension(self):
        self.dimension_questions[-1].q_type = QuestionType.TEXT
        self.dimension_questions[-1].is_required = False
        self.dimension_questions[-1].save(update_fields=["q_type", "is_required"])

        with self.assertRaisesMessage(
            ValidationError,
            "EQ-5D-5L 五个健康维度必须均为单选题",
        ):
            QuestionnaireSubmissionService.submit_questionnaire(
                patient_id=self.patient.id,
                questionnaire_id=self.questionnaire.id,
                answers_data=self._answers()[:-1],
            )

    def test_eq5d5l_rejects_non_numeric_level_configuration(self):
        selected_option = self.dimension_options[0][1]
        selected_option.value = "轻微"
        selected_option.save(update_fields=["value"])

        with self.assertRaisesMessage(
            ValidationError,
            "EQ-5D-5L 每个健康维度必须完整配置 1 至 5 五个等级",
        ):
            QuestionnaireSubmissionService.submit_questionnaire(
                patient_id=self.patient.id,
                questionnaire_id=self.questionnaire.id,
                answers_data=self._answers(),
            )

    def test_eq5d5l_rejects_question_with_missing_level_configuration(self):
        self.dimension_options[0][-1].delete()

        with self.assertRaisesMessage(
            ValidationError,
            "EQ-5D-5L 每个健康维度必须完整配置 1 至 5 五个等级",
        ):
            QuestionnaireSubmissionService.submit_questionnaire(
                patient_id=self.patient.id,
                questionnaire_id=self.questionnaire.id,
                answers_data=self._answers(levels=(1, 1, 1, 1, 1)),
            )

    def test_eq5d5l_rejects_question_with_duplicate_level_configuration(self):
        duplicate_option = self.dimension_options[0][-1]
        duplicate_option.value = "4"
        duplicate_option.save(update_fields=["value"])

        with self.assertRaisesMessage(
            ValidationError,
            "EQ-5D-5L 每个健康维度必须完整配置 1 至 5 五个等级",
        ):
            QuestionnaireSubmissionService.submit_questionnaire(
                patient_id=self.patient.id,
                questionnaire_id=self.questionnaire.id,
                answers_data=self._answers(levels=(1, 1, 1, 1, 1)),
            )

    def test_similar_code_does_not_activate_eq5d5l_value_set(self):
        self.questionnaire.code = "Q_EQ5D5L_CUSTOM"
        self.questionnaire.save(update_fields=["code"])

        submission = QuestionnaireSubmissionService.submit_questionnaire(
            patient_id=self.patient.id,
            questionnaire_id=self.questionnaire.id,
            answers_data=self._answers(),
        )

        self.assertEqual(submission.total_score, Decimal("495.00"))

    @patch(
        "health_data.services.questionnaire_submission.HealthMetricService.save_manual_metric",
        side_effect=RuntimeError("指标写入失败"),
    )
    def test_metric_failure_rolls_back_submission_answers_and_task(self, _mock_save):
        task = DailyTask.objects.create(
            patient=self.patient,
            task_date=timezone.localdate(),
            task_type=choices.PlanItemCategory.QUESTIONNAIRE,
            title="EQ5D5L随访问卷",
            status=choices.TaskStatus.PENDING,
        )

        with self.assertRaisesMessage(RuntimeError, "指标写入失败"):
            QuestionnaireSubmissionService.submit_questionnaire(
                patient_id=self.patient.id,
                questionnaire_id=self.questionnaire.id,
                answers_data=self._answers(),
            )

        task.refresh_from_db()
        self.assertEqual(task.status, choices.TaskStatus.PENDING)
        self.assertEqual(QuestionnaireSubmission.objects.count(), 0)
        self.assertEqual(QuestionnaireAnswer.objects.count(), 0)
        self.assertEqual(HealthMetric.objects.count(), 0)


class EqvasQuestionnaireSubmissionTests(TestCase):
    def setUp(self):
        self.patient = PatientProfile.objects.create(
            phone="13800008889",
            name="EQ-VAS测试患者",
        )
        self.questionnaire = Questionnaire.objects.create(
            name="EQVAS量表",
            code="Q_EQVAS",
            calculation_strategy="SUM",
        )
        self.vas_question = QuestionnaireQuestion.objects.create(
            questionnaire=self.questionnaire,
            text="EQ-VAS自评",
            q_type=QuestionType.TEXT,
            is_required=True,
            seq=0,
        )

    def _answers(self, value="78"):
        return [{"question_id": self.vas_question.id, "value_text": value}]

    def test_eqvas_stores_input_as_answer_submission_score_and_metric(self):
        for value in ("0", "1", "100"):
            with self.subTest(value=value):
                submission = QuestionnaireSubmissionService.submit_questionnaire(
                    patient_id=self.patient.id,
                    questionnaire_id=self.questionnaire.id,
                    answers_data=self._answers(value),
                )
                self.assertEqual(submission.total_score, Decimal(value))
                answer = QuestionnaireAnswer.objects.get(submission=submission)
                self.assertIsNone(answer.option_id)
                self.assertEqual(answer.value_text, value)
                self.assertEqual(
                    HealthMetric.objects.get(
                        questionnaire_submission=submission
                    ).value_main,
                    Decimal(value),
                )

    def test_eqvas_rejects_invalid_values_without_partial_writes(self):
        task = DailyTask.objects.create(
            patient=self.patient,
            task_date=timezone.localdate(),
            task_type=choices.PlanItemCategory.QUESTIONNAIRE,
            title="EQVAS随访问卷",
            status=choices.TaskStatus.PENDING,
        )
        for value in ("-1", "101", "1.5", "1e2", "+1", " 1", "1 ", "一"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                QuestionnaireSubmissionService.submit_questionnaire(
                    patient_id=self.patient.id,
                    questionnaire_id=self.questionnaire.id,
                    answers_data=self._answers(value),
                )

        self.assertEqual(QuestionnaireSubmission.objects.count(), 0)
        self.assertEqual(QuestionnaireAnswer.objects.count(), 0)
        self.assertEqual(HealthMetric.objects.count(), 0)
        task.refresh_from_db()
        self.assertEqual(task.status, choices.TaskStatus.PENDING)

    def test_eqvas_required_question_rejects_empty_answers(self):
        with self.assertRaises(ValidationError):
            QuestionnaireSubmissionService.submit_questionnaire(
                patient_id=self.patient.id,
                questionnaire_id=self.questionnaire.id,
                answers_data=[],
            )

    def test_eqvas_rejects_non_list_answers_even_when_question_is_optional(self):
        self.vas_question.is_required = False
        self.vas_question.save(update_fields=["is_required"])

        for answers_data in (None, {}, 1, ""):
            with self.subTest(answers_data=answers_data), self.assertRaises(
                ValidationError
            ):
                QuestionnaireSubmissionService.submit_questionnaire(
                    patient_id=self.patient.id,
                    questionnaire_id=self.questionnaire.id,
                    answers_data=answers_data,
                )

        self.assertEqual(QuestionnaireSubmission.objects.count(), 0)

    def test_eqvas_optional_blank_saves_zero_without_answer(self):
        self.vas_question.is_required = False
        self.vas_question.save(update_fields=["is_required"])
        task = DailyTask.objects.create(
            patient=self.patient,
            task_date=timezone.localdate(),
            task_type=choices.PlanItemCategory.QUESTIONNAIRE,
            title="EQVAS随访问卷",
            status=choices.TaskStatus.PENDING,
        )

        submission = QuestionnaireSubmissionService.submit_questionnaire(
            patient_id=self.patient.id,
            questionnaire_id=self.questionnaire.id,
            answers_data=[],
        )

        self.assertEqual(submission.total_score, Decimal("0.00"))
        self.assertFalse(submission.answers.exists())
        self.assertEqual(
            HealthMetric.objects.get(
                questionnaire_submission=submission
            ).value_main,
            Decimal("0.00"),
        )
        task.refresh_from_db()
        self.assertEqual(task.status, choices.TaskStatus.COMPLETED)

    def test_eqvas_requires_exact_one_text_question(self):
        QuestionnaireQuestion.objects.create(
            questionnaire=self.questionnaire,
            text="多余题目",
            q_type=QuestionType.TEXT,
            is_required=False,
            seq=1,
        )

        with self.assertRaisesMessage(
            ValidationError,
            "EQ-VAS 问卷必须恰好配置一道题",
        ):
            QuestionnaireSubmissionService.submit_questionnaire(
                patient_id=self.patient.id,
                questionnaire_id=self.questionnaire.id,
                answers_data=self._answers(),
            )

    def test_similar_code_does_not_activate_eqvas_numeric_rule(self):
        self.questionnaire.code = "Q_EQVAS_CUSTOM"
        self.questionnaire.save(update_fields=["code"])

        submission = QuestionnaireSubmissionService.submit_questionnaire(
            patient_id=self.patient.id,
            questionnaire_id=self.questionnaire.id,
            answers_data=self._answers("患者自由文本"),
        )

        self.assertEqual(submission.total_score, Decimal("0.00"))
        self.assertEqual(submission.answers.get().value_text, "患者自由文本")
