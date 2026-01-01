from datetime import date, datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from core.models import DailyTask, Questionnaire, QuestionnaireOption, QuestionnaireQuestion, choices
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
        DailyTask.objects.create(
            patient=self.patient,
            task_date=timezone.now().date(),
            task_type=choices.PlanItemCategory.QUESTIONNAIRE,
            title="随访问卷",
            status=choices.TaskStatus.PENDING,
        )
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
        self.assertEqual(
            DailyTask.objects.filter(
                patient=self.patient,
                task_type=choices.PlanItemCategory.QUESTIONNAIRE,
                status=choices.TaskStatus.COMPLETED,
            ).count(),
            1,
        )

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

    def test_get_submission_dates_returns_unique_dates_desc(self):
        """
        查询提交日期：同一天只保留一次，且最近日期排在最前。
        """
        tz = timezone.get_current_timezone()

        submission_1 = QuestionnaireSubmission.objects.create(
            patient=self.patient,
            questionnaire=self.questionnaire,
        )
        submission_2 = QuestionnaireSubmission.objects.create(
            patient=self.patient,
            questionnaire=self.questionnaire,
        )
        submission_3 = QuestionnaireSubmission.objects.create(
            patient=self.patient,
            questionnaire=self.questionnaire,
        )
        submission_4 = QuestionnaireSubmission.objects.create(
            patient=self.patient,
            questionnaire=self.questionnaire,
        )

        dt_1 = timezone.make_aware(datetime(2025, 1, 10, 9, 0), tz)
        dt_2 = timezone.make_aware(datetime(2025, 1, 10, 20, 0), tz)
        dt_3 = timezone.make_aware(datetime(2025, 1, 8, 8, 30), tz)
        dt_4 = timezone.make_aware(datetime(2025, 2, 1, 9, 0), tz)

        QuestionnaireSubmission.objects.filter(id=submission_1.id).update(
            created_at=dt_1
        )
        QuestionnaireSubmission.objects.filter(id=submission_2.id).update(
            created_at=dt_2
        )
        QuestionnaireSubmission.objects.filter(id=submission_3.id).update(
            created_at=dt_3
        )
        QuestionnaireSubmission.objects.filter(id=submission_4.id).update(
            created_at=dt_4
        )

        dates = QuestionnaireSubmissionService.get_submission_dates(
            patient=self.patient,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
        )

        self.assertEqual(dates, [date(2025, 1, 10), date(2025, 1, 8)])

    def test_list_daily_questionnaire_summaries_latest_per_questionnaire(self):
        """
        查询指定日期摘要：每份问卷仅保留当天最新提交，上一份不含当日。
        """
        tz = timezone.get_current_timezone()
        questionnaire_2 = Questionnaire.objects.create(
            name="测试问卷2",
            code="Q_TEST_2",
            sort_order=1,
        )

        q1_prev = QuestionnaireSubmission.objects.create(
            patient=self.patient,
            questionnaire=self.questionnaire,
            total_score=Decimal("3.00"),
        )
        q1_early = QuestionnaireSubmission.objects.create(
            patient=self.patient,
            questionnaire=self.questionnaire,
            total_score=Decimal("4.00"),
        )
        q1_late = QuestionnaireSubmission.objects.create(
            patient=self.patient,
            questionnaire=self.questionnaire,
            total_score=Decimal("6.00"),
        )
        q2_prev = QuestionnaireSubmission.objects.create(
            patient=self.patient,
            questionnaire=questionnaire_2,
            total_score=Decimal("2.00"),
        )
        q2_current = QuestionnaireSubmission.objects.create(
            patient=self.patient,
            questionnaire=questionnaire_2,
            total_score=Decimal("5.00"),
        )

        QuestionnaireSubmission.objects.filter(id=q1_prev.id).update(
            created_at=timezone.make_aware(datetime(2025, 1, 8, 9, 0), tz)
        )
        QuestionnaireSubmission.objects.filter(id=q1_early.id).update(
            created_at=timezone.make_aware(datetime(2025, 1, 10, 9, 0), tz)
        )
        QuestionnaireSubmission.objects.filter(id=q1_late.id).update(
            created_at=timezone.make_aware(datetime(2025, 1, 10, 20, 0), tz)
        )
        QuestionnaireSubmission.objects.filter(id=q2_prev.id).update(
            created_at=timezone.make_aware(datetime(2025, 1, 5, 8, 0), tz)
        )
        QuestionnaireSubmission.objects.filter(id=q2_current.id).update(
            created_at=timezone.make_aware(datetime(2025, 1, 10, 10, 0), tz)
        )

        summaries = QuestionnaireSubmissionService.list_daily_questionnaire_summaries(
            patient_id=self.patient.id,
            target_date=date(2025, 1, 10),
        )

        self.assertEqual(len(summaries), 2)
        self.assertEqual(
            [item["questionnaire_id"] for item in summaries],
            [self.questionnaire.id, questionnaire_2.id],
        )

        q1_summary = summaries[0]
        self.assertEqual(q1_summary["submission_id"], q1_late.id)
        self.assertEqual(q1_summary["prev_submission_id"], q1_prev.id)
        self.assertEqual(q1_summary["score_change"], Decimal("3.00"))
        self.assertEqual(q1_summary["change_type"], "up")

        q2_summary = summaries[1]
        self.assertEqual(q2_summary["submission_id"], q2_current.id)
        self.assertEqual(q2_summary["prev_submission_id"], q2_prev.id)

    def test_get_questionnaire_comparison_returns_question_details(self):
        """
        查询问卷对比：返回题目明细与分数变化。
        """
        prev_submission = QuestionnaireSubmissionService.submit_questionnaire(
            patient_id=self.patient.id,
            questionnaire_id=self.questionnaire.id,
            answers_data=[
                {"option_id": self.q1_opt1.id},
                {"option_id": self.q2_opt1.id},
            ],
        )
        current_submission = QuestionnaireSubmissionService.submit_questionnaire(
            patient_id=self.patient.id,
            questionnaire_id=self.questionnaire.id,
            answers_data=[
                {"option_id": self.q1_opt2.id},
                {"option_id": self.q2_opt2.id},
            ],
        )

        tz = timezone.get_current_timezone()
        QuestionnaireSubmission.objects.filter(id=prev_submission.id).update(
            created_at=timezone.make_aware(datetime(2025, 1, 8, 9, 0), tz)
        )
        QuestionnaireSubmission.objects.filter(id=current_submission.id).update(
            created_at=timezone.make_aware(datetime(2025, 1, 10, 10, 0), tz)
        )

        comparison = QuestionnaireSubmissionService.get_questionnaire_comparison(
            submission_id=current_submission.id
        )

        self.assertEqual(comparison["questionnaire_id"], self.questionnaire.id)
        self.assertEqual(comparison["current_score"], Decimal("6.00"))
        self.assertEqual(comparison["prev_score"], Decimal("4.00"))
        self.assertEqual(comparison["change_type"], "up")
        self.assertEqual(comparison["change_text"], "较上次提升2分")

        questions = comparison["questions"]
        self.assertEqual(len(questions), 2)
        self.assertEqual(questions[0]["current_answer"], self.q1_opt2.text)
        self.assertEqual(questions[0]["prev_answer"], self.q1_opt1.text)
        self.assertEqual(questions[0]["change_text"], "提升1分")


class QuestionnaireSubmissionGradeTest(TestCase):
    def setUp(self) -> None:
        self.patient = PatientProfile.objects.create(
            phone="13800000001",
            name="分级测试患者",
        )

    def _get_or_create_questionnaire(self, code: str, name: str) -> Questionnaire:
        questionnaire = Questionnaire.objects.filter(code=code).first()
        if questionnaire:
            return questionnaire
        return Questionnaire.objects.create(name=name, code=code)

    def _create_submission(
        self, questionnaire: Questionnaire, total_score: str
    ) -> QuestionnaireSubmission:
        return QuestionnaireSubmission.objects.create(
            patient=self.patient,
            questionnaire=questionnaire,
            total_score=Decimal(total_score),
        )

    def test_grade_physical(self):
        questionnaire = self._get_or_create_questionnaire("Q_PHYSICAL", "体能评分")
        submission = self._create_submission(questionnaire, "1")

        self.assertEqual(
            QuestionnaireSubmissionService.get_submission_grade(submission.id),
            1,
        )

    def test_grade_breath(self):
        questionnaire = self._get_or_create_questionnaire("Q_BREATH", "呼吸困难评估")
        submission = self._create_submission(questionnaire, "3")

        self.assertEqual(
            QuestionnaireSubmissionService.get_submission_grade(submission.id),
            3,
        )

    def test_grade_cough_bleeding_forces_red(self):
        questionnaire = self._get_or_create_questionnaire("Q_COUGH", "咳嗽评估")
        question = QuestionnaireQuestion.objects.filter(
            id=QuestionnaireSubmissionService.COUGH_BLOOD_QUESTION_ID
        ).first()
        if not question:
            question = QuestionnaireQuestion.objects.create(
                id=QuestionnaireSubmissionService.COUGH_BLOOD_QUESTION_ID,
                questionnaire=questionnaire,
                text="痰中带血",
                seq=1,
                is_required=True,
            )
        option = QuestionnaireOption.objects.create(
            question=question,
            text="高风险",
            score=Decimal("9"),
            seq=1,
        )
        submission = self._create_submission(questionnaire, "3")
        QuestionnaireAnswer.objects.create(
            submission=submission,
            question=question,
            option=option,
        )

        self.assertEqual(
            QuestionnaireSubmissionService.get_submission_grade(submission.id),
            4,
        )

    def test_grade_appetite(self):
        questionnaire = self._get_or_create_questionnaire("Q_APPETITE", "食欲评估")
        submission = self._create_submission(questionnaire, "9")

        self.assertEqual(
            QuestionnaireSubmissionService.get_submission_grade(submission.id),
            3,
        )

    def test_grade_pain_three_sites_max(self):
        questionnaire = self._get_or_create_questionnaire("Q_PAIN", "疼痛评估")
        submission = self._create_submission(questionnaire, "18")

        questions = [
            QuestionnaireQuestion.objects.create(
                questionnaire=questionnaire,
                text=f"部位{i}",
                seq=i,
                is_required=True,
            )
            for i in range(1, 4)
        ]
        for question in questions:
            option = QuestionnaireOption.objects.create(
                question=question,
                text="重度",
                score=Decimal("9"),
                seq=1,
            )
            QuestionnaireAnswer.objects.create(
                submission=submission,
                question=question,
                option=option,
            )

        self.assertEqual(
            QuestionnaireSubmissionService.get_submission_grade(submission.id),
            4,
        )

    def test_grade_sleep(self):
        questionnaire = self._get_or_create_questionnaire("Q_SLEEP", "睡眠评估")
        submission = self._create_submission(questionnaire, "20")

        self.assertEqual(
            QuestionnaireSubmissionService.get_submission_grade(submission.id),
            1,
        )

    def test_grade_depressive(self):
        questionnaire = self._get_or_create_questionnaire("Q_DEPRESSIVE", "抑郁评估")
        submission = self._create_submission(questionnaire, "12")

        self.assertEqual(
            QuestionnaireSubmissionService.get_submission_grade(submission.id),
            3,
        )

    def test_grade_anxiety(self):
        questionnaire = self._get_or_create_questionnaire("Q_ANXIETY", "焦虑评估")
        submission = self._create_submission(questionnaire, "15")

        self.assertEqual(
            QuestionnaireSubmissionService.get_submission_grade(submission.id),
            4,
        )
