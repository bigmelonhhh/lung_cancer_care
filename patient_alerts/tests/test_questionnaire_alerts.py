from decimal import Decimal

from django.test import TestCase

from core.models import (
    Questionnaire,
    QuestionnaireCode,
    QuestionnaireOption,
    QuestionnaireQuestion,
)
from core.models.choices import QuestionType
from health_data.models import QuestionnaireAnswer, QuestionnaireSubmission
from patient_alerts.models import (
    AlertEventType,
    AlertLevel,
    PatientAlert,
    PatientAlertSource,
)
from patient_alerts.services.questionnaire_alerts import QuestionnaireAlertService
from users.models import PatientProfile


class QuestionnaireAlertServiceTests(TestCase):
    def setUp(self):
        self.patient = PatientProfile.objects.create(phone="18600000111")

    def _get_questionnaire(self, code: str, name: str) -> Questionnaire:
        questionnaire, _ = Questionnaire.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "calculation_strategy": "SUM",
            },
        )
        return questionnaire

    def test_alert_created_when_grade_is_mild(self):
        questionnaire = self._get_questionnaire(QuestionnaireCode.Q_PHYSICAL, "体能评分")
        submission = QuestionnaireSubmission.objects.create(
            patient=self.patient,
            questionnaire=questionnaire,
            total_score=Decimal("2.00"),
        )

        alert = QuestionnaireAlertService.process_submission(submission)

        self.assertIsNotNone(alert)
        self.assertEqual(alert.event_type, AlertEventType.QUESTIONNAIRE)
        self.assertEqual(alert.event_level, AlertLevel.MILD)

    def test_no_alert_when_grade_is_normal(self):
        questionnaire = self._get_questionnaire(QuestionnaireCode.Q_PHYSICAL, "体能评分")
        submission = QuestionnaireSubmission.objects.create(
            patient=self.patient,
            questionnaire=questionnaire,
            total_score=Decimal("1.00"),
        )

        alert = QuestionnaireAlertService.process_submission(submission)

        self.assertIsNone(alert)

    def test_alerts_for_all_questionnaires(self):
        cases = [
            (QuestionnaireCode.Q_PHYSICAL, "体能评分", Decimal("2.00"), AlertLevel.MILD),
            (QuestionnaireCode.Q_BREATH, "呼吸困难评估", Decimal("2.00"), AlertLevel.MILD),
            (QuestionnaireCode.Q_COUGH, "咳嗽与痰色评估", Decimal("9.00"), AlertLevel.SEVERE),
            (QuestionnaireCode.Q_APPETITE, "食欲评估", Decimal("4.00"), AlertLevel.MILD),
            (QuestionnaireCode.Q_PAIN, "身体疼痛评估", Decimal("9.00"), AlertLevel.MODERATE),
            (QuestionnaireCode.Q_SLEEP, "睡眠质量评估", Decimal("30.00"), AlertLevel.MODERATE),
            (QuestionnaireCode.Q_DEPRESSIVE, "抑郁评估", Decimal("5.00"), AlertLevel.MILD),
            (QuestionnaireCode.Q_ANXIETY, "焦虑评估", Decimal("5.00"), AlertLevel.MILD),
            (QuestionnaireCode.Q_KQNMLB, "口腔黏膜损伤自评量表", Decimal("1.00"), AlertLevel.MILD),
            (QuestionnaireCode.Q_KQNMLB, "口腔黏膜损伤自评量表", Decimal("5.00"), AlertLevel.MODERATE),
            (QuestionnaireCode.Q_KQNMLB, "口腔黏膜损伤自评量表", Decimal("10.00"), AlertLevel.SEVERE),
        ]

        for code, name, score, expected_level in cases:
            with self.subTest(code=code):
                questionnaire = self._get_questionnaire(code, name)
                submission = QuestionnaireSubmission.objects.create(
                    patient=self.patient,
                    questionnaire=questionnaire,
                    total_score=score,
                )
                alert = QuestionnaireAlertService.process_submission(submission)
                self.assertIsNotNone(alert)
                self.assertEqual(alert.event_type, AlertEventType.QUESTIONNAIRE)
                self.assertEqual(alert.event_level, expected_level)

    def test_questionnaire_alert_records_submission_source(self):
        questionnaire = self._get_questionnaire(
            QuestionnaireCode.Q_COUGH,
            "咳嗽与痰色评估",
        )
        submission = QuestionnaireSubmission.objects.create(
            patient=self.patient,
            questionnaire=questionnaire,
            total_score=Decimal("9.00"),
        )

        alert = QuestionnaireAlertService.process_submission(submission)

        source = PatientAlertSource.objects.get(alert=alert)
        self.assertEqual(source.patient_id, self.patient.id)
        self.assertEqual(source.source_type, "questionnaire")
        self.assertEqual(source.source_id, submission.id)
        self.assertEqual(source.source_key, f"questionnaire:{submission.id}")
        self.assertEqual(source.source_label, "咳嗽与痰色评估")
        self.assertEqual(source.value_display, "总分 9，分级 4级")
        self.assertEqual(source.event_level, AlertLevel.SEVERE)
        self.assertEqual(source.source_payload["questionnaire_code"], QuestionnaireCode.Q_COUGH)

    def test_no_alert_when_oral_mucosa_score_is_zero(self):
        questionnaire = self._get_questionnaire(
            QuestionnaireCode.Q_KQNMLB,
            "口腔黏膜损伤自评量表",
        )
        submission = QuestionnaireSubmission.objects.create(
            patient=self.patient,
            questionnaire=questionnaire,
            total_score=Decimal("0.00"),
        )

        alert = QuestionnaireAlertService.process_submission(submission)

        self.assertIsNone(alert)

    def test_eq5d5l_alert_uses_dimension_grade_and_auditable_payload(self):
        questionnaire = self._get_questionnaire("Q_EQ5D5L", "EQ-5D-5L量表")
        levels = (2, 1, 3, 2, 4)
        dimension_names = ("行动能力", "自我照顾", "日常活动", "疼痛/不适", "焦虑/抑郁")
        submission = QuestionnaireSubmission.objects.create(
            patient=self.patient,
            questionnaire=questionnaire,
            total_score=Decimal("0.55"),
        )
        for seq, (name, level) in enumerate(zip(dimension_names, levels)):
            question = QuestionnaireQuestion.objects.create(
                questionnaire=questionnaire,
                text=name,
                q_type=QuestionType.SINGLE,
                seq=seq,
            )
            option = QuestionnaireOption.objects.create(
                question=question,
                text=f"{level}级",
                value=str(level),
                score=0,
                seq=level,
            )
            QuestionnaireAnswer.objects.create(
                submission=submission,
                question=question,
                option=option,
            )

        alert = QuestionnaireAlertService.process_submission(submission)

        self.assertIsNotNone(alert)
        self.assertEqual(alert.event_level, AlertLevel.SEVERE)
        self.assertEqual(alert.event_title, "EQ-5D-5L量表异常")
        self.assertEqual(
            alert.event_content,
            "健康状态21324，健康效用指数0.55，最严重维度为焦虑/抑郁（4级）。",
        )
        source = PatientAlertSource.objects.get(alert=alert)
        self.assertEqual(source.value_display, alert.event_content)
        self.assertEqual(source.source_payload["health_state"], "21324")
        self.assertEqual(source.source_payload["utility_index"], "0.55")
        self.assertEqual(source.source_payload["max_dimension_level"], 4)
        self.assertEqual(source.source_payload["max_dimensions"], ["焦虑/抑郁"])
        self.assertEqual(
            source.source_payload["grading_rule"],
            "EQ5D5L_MAX_DIMENSION_V1",
        )

    def test_eqvas_alert_uses_absolute_grade_and_special_content(self):
        questionnaire = self._get_questionnaire("Q_EQVAS", "EQ-VAS量表")
        question = QuestionnaireQuestion.objects.create(
            questionnaire=questionnaire,
            text="EQ-VAS自评",
            q_type=QuestionType.TEXT,
            seq=0,
        )
        submission = QuestionnaireSubmission.objects.create(
            patient=self.patient,
            questionnaire=questionnaire,
            total_score=Decimal("58.00"),
        )
        QuestionnaireAnswer.objects.create(
            submission=submission,
            question=question,
            value_text="58",
        )

        alert = QuestionnaireAlertService.process_submission(submission)

        self.assertIsNotNone(alert)
        self.assertEqual(alert.event_level, AlertLevel.MODERATE)
        self.assertEqual(alert.event_title, "EQ-VAS评分异常")
        self.assertEqual(
            alert.event_content,
            "EQ-VAS评分58分，当前为3级中度。",
        )
        source = PatientAlertSource.objects.get(alert=alert)
        self.assertEqual(source.value_display, alert.event_content)
        self.assertEqual(source.source_payload["vas_score"], 58)
        self.assertEqual(
            source.source_payload["grading_rule"],
            "EQVAS_ABSOLUTE_A_V1",
        )

    def test_eqvas_optional_blank_does_not_create_alert(self):
        questionnaire = self._get_questionnaire("Q_EQVAS", "EQ-VAS量表")
        QuestionnaireQuestion.objects.create(
            questionnaire=questionnaire,
            text="EQ-VAS自评",
            q_type=QuestionType.TEXT,
            is_required=False,
            seq=0,
        )
        submission = QuestionnaireSubmission.objects.create(
            patient=self.patient,
            questionnaire=questionnaire,
            total_score=Decimal("0.00"),
        )

        alert = QuestionnaireAlertService.process_submission(submission)

        self.assertIsNone(alert)
        self.assertFalse(PatientAlert.objects.exists())
