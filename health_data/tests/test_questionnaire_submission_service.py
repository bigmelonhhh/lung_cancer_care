from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from core.models import Questionnaire, QuestionnaireOption, QuestionnaireQuestion
from health_data.models import (
    HealthMetric,
    MetricSource,
    QuestionnaireAnswer,
    QuestionnaireSubmission,
)
from health_data.services.questionnaire_submission import QuestionnaireSubmissionService
from users.models import PatientProfile


class QuestionnaireSubmissionServiceTest(TestCase):
    def setUp(self) -> None:
        # 创建一个简单的患者档案
        self.patient = PatientProfile.objects.create(
            phone="13800000000",
            name="测试患者",
        )

        # 创建问卷及两道必答题，每题两个选项
        self.questionnaire = Questionnaire.objects.create(
            name="测试问卷",
            code="Q_TEST",
        )

        self.q1 = QuestionnaireQuestion.objects.create(
            questionnaire=self.questionnaire,
            text="问题1",
            is_required=True,
            seq=1,
        )
        self.q2 = QuestionnaireQuestion.objects.create(
            questionnaire=self.questionnaire,
            text="问题2",
            is_required=True,
            seq=2,
        )

        # 每题两个选项，分值分别为 1 / 2
        self.q1_opt1 = QuestionnaireOption.objects.create(
            question=self.q1,
            text="Q1-选项1",
            score=Decimal("1"),
            seq=1,
        )
        self.q1_opt2 = QuestionnaireOption.objects.create(
            question=self.q1,
            text="Q1-选项2",
            score=Decimal("2"),
            seq=2,
        )
        self.q2_opt1 = QuestionnaireOption.objects.create(
            question=self.q2,
            text="Q2-选项1",
            score=Decimal("3"),
            seq=1,
        )
        self.q2_opt2 = QuestionnaireOption.objects.create(
            question=self.q2,
            text="Q2-选项2",
            score=Decimal("4"),
            seq=2,
        )

    def test_submit_questionnaire_success_sum_score_and_create_answers(self):
        """
        正常提交：答完所有题目，生成提交记录和明细，并正确计算总分。
        """
        answers_data = [
            {"option_id": self.q1_opt2.id},  # 问题1 选分值为 2 的选项
            {"option_id": self.q2_opt1.id},  # 问题2 选分值为 3 的选项
        ]

        submission = QuestionnaireSubmissionService.submit_questionnaire(
            patient_id=self.patient.id,
            questionnaire_id=self.questionnaire.id,
            answers_data=answers_data,
        )

        # 提交记录已创建
        self.assertIsInstance(submission, QuestionnaireSubmission)
        self.assertEqual(submission.patient_id, self.patient.id)
        self.assertEqual(submission.questionnaire_id, self.questionnaire.id)

        # 总分为所选两个选项分值之和：2 + 3 = 5
        self.assertEqual(submission.total_score, Decimal("5"))

        # 明细记录正确写入，且 question 来源于 option.question
        answers = QuestionnaireAnswer.objects.filter(submission=submission).order_by(
            "id"
        )
        self.assertEqual(answers.count(), 2)

        self.assertEqual(answers[0].option_id, self.q1_opt2.id)
        self.assertEqual(answers[0].question_id, self.q1.id)

        self.assertEqual(answers[1].option_id, self.q2_opt1.id)
        self.assertEqual(answers[1].question_id, self.q2.id)

    def test_submit_questionnaire_missing_question_raises_validation_error(self):
        """
        少答题目时应抛出 ValidationError，且不产生提交记录。
        """
        # 只答第一题，第二题缺失
        answers_data = [
            {"option_id": self.q1_opt1.id},
        ]

        with self.assertRaises(ValidationError):
            QuestionnaireSubmissionService.submit_questionnaire(
                patient_id=self.patient.id,
                questionnaire_id=self.questionnaire.id,
                answers_data=answers_data,
            )

        # 不应有提交记录写入
        self.assertEqual(QuestionnaireSubmission.objects.count(), 0)

    def test_submit_questionnaire_creates_health_metric_with_total_score(self):
        """
        提交成功后，应在 HealthMetric 中写入一条总分记录：
        - metric_type 使用 questionnaire.code；
        - value_main 为 total_score；
        - source 为 MANUAL；
        - questionnaire_submission 外键指向当前提交。
        """
        answers_data = [
            {"option_id": self.q1_opt2.id},  # 分值 2
            {"option_id": self.q2_opt1.id},  # 分值 3
        ]

        submission = QuestionnaireSubmissionService.submit_questionnaire(
            patient_id=self.patient.id,
            questionnaire_id=self.questionnaire.id,
            answers_data=answers_data,
        )

        # 预期总分 2 + 3 = 5
        self.assertEqual(submission.total_score, Decimal("5"))

        metrics = HealthMetric.objects.filter(
            patient_id=self.patient.id,
            metric_type=self.questionnaire.code,
            questionnaire_submission=submission,
        )
        self.assertEqual(metrics.count(), 1)

        metric = metrics.first()
        self.assertEqual(metric.value_main, Decimal("5"))
        self.assertEqual(metric.source, MetricSource.MANUAL)
