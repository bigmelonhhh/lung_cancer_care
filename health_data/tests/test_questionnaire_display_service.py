from datetime import date, datetime, timedelta
from decimal import Decimal

from django.test import TestCase
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from core.models import Questionnaire, QuestionnaireOption, QuestionnaireQuestion
from health_data.models import QuestionnaireSubmission
from health_data.services.questionnaire_display import QuestionnaireDisplayService
from patient_alerts.models import AlertEventType, AlertLevel, PatientAlert
from users.models import PatientProfile


class QuestionnaireDisplayServiceTests(TestCase):
    def setUp(self):
        Questionnaire.objects.update(is_active=False)
        self.patient = PatientProfile.objects.create(
            phone="13800009001",
            name="动态问卷患者",
        )
        self.other_patient = PatientProfile.objects.create(
            phone="13800009002",
            name="其他患者",
        )
        self.start_date = date(2026, 7, 1)
        self.end_date = date(2026, 7, 31)
        tz = timezone.get_current_timezone()
        self.start_at = timezone.make_aware(
            datetime.combine(self.start_date, datetime.min.time()), tz
        )
        self.end_at = timezone.make_aware(
            datetime.combine(self.end_date + timedelta(days=1), datetime.min.time()), tz
        )

        self.active = Questionnaire.objects.create(
            name="术后呼吸恢复问卷",
            code="Q_DYNAMIC_BREATH",
            is_active=True,
            sort_order=20,
        )
        question = QuestionnaireQuestion.objects.create(
            questionnaire=self.active,
            text="呼吸困难程度",
            seq=1,
        )
        QuestionnaireOption.objects.create(
            question=question,
            text="没有",
            score=Decimal("0"),
            seq=1,
        )
        QuestionnaireOption.objects.create(
            question=question,
            text="明显",
            score=Decimal("4"),
            seq=2,
        )
        self.empty_active = Questionnaire.objects.create(
            name="生活质量随访问卷",
            code="Q_DYNAMIC_LIFE",
            is_active=True,
            sort_order=30,
        )
        self.inactive = Questionnaire.objects.create(
            name="停用问卷",
            code="Q_DYNAMIC_INACTIVE",
            is_active=False,
            sort_order=10,
        )

    def _submission(self, questionnaire, patient, score, created_at):
        submission = QuestionnaireSubmission.objects.create(
            patient=patient,
            questionnaire=questionnaire,
            total_score=Decimal(score),
        )
        QuestionnaireSubmission.objects.filter(pk=submission.pk).update(
            created_at=created_at
        )
        submission.refresh_from_db()
        return submission

    def test_patient_archive_cards_only_include_active_questionnaires_with_records(self):
        self._submission(
            self.active,
            self.patient,
            "3",
            self.start_at + timedelta(days=2),
        )
        self._submission(
            self.inactive,
            self.patient,
            "2",
            self.start_at + timedelta(days=3),
        )
        self._submission(
            self.empty_active,
            self.other_patient,
            "1",
            self.start_at + timedelta(days=4),
        )
        self._submission(
            self.empty_active,
            self.patient,
            "1",
            self.start_at - timedelta(days=1),
        )
        PatientAlert.objects.create(
            patient=self.patient,
            event_type=AlertEventType.QUESTIONNAIRE,
            event_level=AlertLevel.MODERATE,
            event_title="术后呼吸恢复问卷异常",
            event_content="测试异常",
            event_time=self.start_at + timedelta(days=2),
            source_type="questionnaire",
            source_payload={"questionnaire_code": self.active.code},
        )

        cards = QuestionnaireDisplayService.build_patient_archive_cards(
            patient=self.patient,
            start_at=self.start_at,
            end_at=self.end_at,
        )

        self.assertEqual([item["questionnaire_id"] for item in cards], [self.active.id])
        self.assertEqual(cards[0]["name"], "术后呼吸恢复问卷")
        self.assertEqual(cards[0]["submission_count"], 1)
        self.assertEqual(cards[0]["latest_score"], Decimal("3.00"))
        self.assertEqual(cards[0]["icon_key"], "breath")
        self.assertEqual(cards[0]["abnormal"], 1)

    def test_special_questionnaire_archive_cards_use_distinct_score_labels(self):
        eq5d5l = Questionnaire.objects.create(
            name="EQ5D5L量表",
            code="Q_EQ5D5L",
            is_active=True,
            sort_order=5,
        )
        eqvas = Questionnaire.objects.create(
            name="EQVAS量表",
            code="Q_EQVAS",
            is_active=True,
            sort_order=6,
        )
        self._submission(
            eq5d5l,
            self.patient,
            "0.55",
            self.start_at + timedelta(days=2),
        )
        self._submission(
            eqvas,
            self.patient,
            "78",
            self.start_at + timedelta(days=3),
        )

        cards = QuestionnaireDisplayService.build_patient_archive_cards(
            patient=self.patient,
            start_at=self.start_at,
            end_at=self.end_at,
        )

        eq5d5l_card = next(
            item for item in cards if item["questionnaire_id"] == eq5d5l.id
        )
        eqvas_card = next(
            item for item in cards if item["questionnaire_id"] == eqvas.id
        )
        self.assertEqual(eq5d5l_card["score_label"], "健康效用指数")
        self.assertEqual(eq5d5l_card["latest_score"], Decimal("0.55"))
        self.assertEqual(eqvas_card["score_label"], "EQ-VAS评分")
        self.assertEqual(eqvas_card["latest_score"], Decimal("78.00"))

    def test_daily_score_charts_include_every_active_questionnaire_and_use_latest_score(self):
        target_day = self.start_date + timedelta(days=5)
        target_at = self.start_at + timedelta(days=5, hours=8)
        self._submission(self.active, self.patient, "1", target_at)
        self._submission(self.active, self.patient, "4", target_at + timedelta(hours=2))
        self._submission(self.inactive, self.patient, "2", target_at)

        charts = QuestionnaireDisplayService.build_daily_score_charts(
            patient=self.patient,
            start_at=self.start_at,
            end_at=self.end_at,
            date_list=[target_day],
        )

        self.assertEqual(
            [item["questionnaire_id"] for item in charts],
            [self.active.id, self.empty_active.id],
        )
        self.assertEqual(charts[0]["series"][0]["data"], [4.0])
        self.assertEqual(charts[1]["series"][0]["data"], [None])
        self.assertEqual(charts[0]["id"], f"chart-questionnaire-{self.active.id}")

    def test_eq5d5l_daily_chart_uses_health_utility_label_and_fixed_bounds(self):
        eq5d5l = Questionnaire.objects.create(
            name="EQ5D5L量表",
            code="Q_EQ5D5L",
            is_active=True,
            sort_order=5,
        )
        self._submission(
            eq5d5l,
            self.patient,
            "-0.39",
            self.start_at + timedelta(days=5),
        )

        charts = QuestionnaireDisplayService.build_daily_score_charts(
            patient=self.patient,
            start_at=self.start_at,
            end_at=self.end_at,
            date_list=[self.start_date + timedelta(days=5)],
        )

        chart = next(
            item for item in charts if item["questionnaire_id"] == eq5d5l.id
        )
        self.assertEqual(chart["y_min"], -0.4)
        self.assertEqual(chart["y_max"], 1.0)
        self.assertEqual(chart["series"][0]["name"], "健康效用指数")

    def test_eqvas_archive_records_and_month_chart_use_vas_semantics(self):
        eqvas = Questionnaire.objects.create(
            name="EQVAS量表",
            code="Q_EQVAS",
            is_active=True,
            sort_order=5,
        )
        self._submission(
            eqvas,
            self.patient,
            "78",
            self.start_at + timedelta(days=5),
        )

        records, _, _, _ = QuestionnaireDisplayService.list_patient_submissions(
            patient=self.patient,
            questionnaire_id=eqvas.id,
            start_at=self.start_at,
            end_at=self.end_at,
            cursor_month="2026-07",
            cursor_offset=0,
            limit=6,
        )
        chart = QuestionnaireDisplayService.build_patient_month_score_chart(
            patient=self.patient,
            questionnaire=eqvas,
            start_at=self.start_at,
            end_at=self.end_at,
            date_list=[self.start_date + timedelta(days=5)],
        )

        self.assertEqual(records[0]["data"][0]["label"], "EQ-VAS评分")
        self.assertEqual(chart["series"][0]["name"], "EQ-VAS评分")
        self.assertEqual((chart["y_min"], chart["y_max"]), (0.0, 100.0))

    def test_monthly_count_charts_include_empty_active_questionnaires(self):
        self._submission(
            self.active,
            self.patient,
            "2",
            self.start_at + timedelta(days=3),
        )
        self._submission(
            self.active,
            self.patient,
            "3",
            self.start_at + timedelta(days=10),
        )

        charts = QuestionnaireDisplayService.build_monthly_count_charts(
            patient=self.patient,
            start_date=self.start_date,
            end_date=self.end_date,
            month_labels=["2026-07"],
        )

        self.assertEqual(len(charts), 2)
        self.assertEqual(charts[0]["series"][0]["data"], [2])
        self.assertEqual(charts[0]["submission_count"], 2)
        self.assertEqual(charts[1]["series"][0]["data"], [0])

    def test_submission_batch_continues_into_previous_month(self):
        july_submission = self._submission(
            self.active,
            self.patient,
            "4",
            self.start_at + timedelta(days=20),
        )
        june_at = self.start_at - timedelta(days=10)
        june_submission = self._submission(
            self.active,
            self.patient,
            "2",
            june_at,
        )

        records, has_more, next_month, next_offset = (
            QuestionnaireDisplayService.list_patient_submissions(
                patient=self.patient,
                questionnaire_id=self.active.id,
                start_at=timezone.make_aware(
                    datetime(2026, 6, 1), timezone.get_current_timezone()
                ),
                end_at=self.end_at,
                cursor_month="2026-07",
                cursor_offset=0,
                limit=6,
            )
        )

        self.assertEqual(
            [item["questionnaire_submission_id"] for item in records],
            [july_submission.id, june_submission.id],
        )
        self.assertFalse(has_more)
        self.assertIsNone(next_month)
        self.assertIsNone(next_offset)

    def test_resolve_visual_uses_safe_semantic_icon_and_generic_fallback(self):
        breath_visual = QuestionnaireDisplayService.resolve_visual(self.active)
        fallback_visual = QuestionnaireDisplayService.resolve_visual(self.empty_active)

        self.assertEqual(breath_visual["icon_key"], "breath")
        self.assertEqual(fallback_visual["icon_key"], "questionnaire")
        self.assertRegex(breath_visual["color"], r"^#[0-9A-F]{6}$")

    def test_daily_chart_query_count_does_not_grow_with_questionnaire_count(self):
        def query_count():
            with CaptureQueriesContext(connection) as queries:
                QuestionnaireDisplayService.build_daily_score_charts(
                    patient=self.patient,
                    start_at=self.start_at,
                    end_at=self.end_at,
                    date_list=[self.start_date],
                )
            return len(queries)

        baseline_count = query_count()
        Questionnaire.objects.bulk_create(
            [
                Questionnaire(
                    name=f"批量问卷 {index}",
                    code=f"Q_BATCH_{index}",
                    is_active=True,
                )
                for index in range(8)
            ]
        )

        self.assertEqual(query_count(), baseline_count)
