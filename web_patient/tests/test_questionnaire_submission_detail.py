from datetime import datetime
from decimal import Decimal
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import (
    Questionnaire,
    QuestionnaireCode,
    QuestionnaireOption,
    QuestionnaireQuestion,
    choices,
)
from health_data.models import HealthMetric, QuestionnaireAnswer, QuestionnaireSubmission
from users.models import CustomUser, PatientProfile


class QuestionnaireSubmissionDetailViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = CustomUser.objects.create_user(
            username="testpatient_questionnaire_submission_detail",
            password="password",
            wx_openid="test_openid_questionnaire_submission_detail",
        )
        self.patient = PatientProfile.objects.create(
            user=self.user, name="Test Patient", phone="13800000021"
        )
        self.client.force_login(self.user)
        self.record_detail_url = reverse("web_patient:health_record_detail")
        self.fallback_url = reverse("web_patient:health_records")
        self.tz = timezone.get_current_timezone()

    def _aware_dt(self, year=2025, month=3, day=10, hour=10, minute=0):
        return timezone.make_aware(datetime(year, month, day, hour, minute), self.tz)

    def _get_or_create_questionnaire(self):
        questionnaire, _ = Questionnaire.objects.get_or_create(
            code=QuestionnaireCode.Q_ANXIETY,
            defaults={"name": "焦虑评估", "is_active": True},
        )
        return questionnaire

    def test_questionnaire_record_shows_detail_button_and_ajax_contains_submission_id(self):
        questionnaire = self._get_or_create_questionnaire()
        submission = QuestionnaireSubmission.objects.create(
            patient=self.patient,
            questionnaire=questionnaire,
            total_score=Decimal("5.00"),
        )
        HealthMetric.objects.create(
            patient=self.patient,
            metric_type=QuestionnaireCode.Q_ANXIETY,
            measured_at=self._aware_dt(),
            value_main=Decimal("5.00"),
            source="manual",
            questionnaire_submission=submission,
        )

        with patch("web_patient.views.record._is_member", return_value=True):
            resp = self.client.get(
                self.record_detail_url,
                {"type": "anxiety", "title": "焦虑评估", "month": "2025-03"},
            )
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, f'data-submission-id="{submission.id}"')
            self.assertContains(resp, 'role="button"')
            self.assertNotContains(resp, "查看详情")

            ajax_resp = self.client.get(
                self.record_detail_url,
                {"type": "anxiety", "title": "焦虑评估", "month": "2025-03"},
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )
            self.assertEqual(ajax_resp.status_code, 200)
            payload = ajax_resp.json()
            self.assertTrue(payload["records"])
            self.assertEqual(
                payload["records"][0]["questionnaire_submission_id"], submission.id
            )

    def test_questionnaire_record_without_submission_id_shows_disabled_detail_button(self):
        self._get_or_create_questionnaire()
        HealthMetric.objects.create(
            patient=self.patient,
            metric_type=QuestionnaireCode.Q_ANXIETY,
            measured_at=self._aware_dt(),
            value_main=Decimal("3.00"),
            source="manual",
        )

        with patch("web_patient.views.record._is_member", return_value=True):
            resp = self.client.get(
                self.record_detail_url,
                {"type": "anxiety", "title": "焦虑评估", "month": "2025-03"},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'data-submission-id=""')
        self.assertContains(resp, 'aria-disabled="true"')
        self.assertNotContains(resp, "查看详情")

    def test_questionnaire_submission_detail_page_renders_single_and_multiple_answers(self):
        questionnaire = self._get_or_create_questionnaire()
        q1 = QuestionnaireQuestion.objects.create(
            questionnaire=questionnaire,
            text="最近是否感到紧张？",
            q_type=choices.QuestionType.SINGLE,
            seq=1,
            is_required=True,
        )
        q2 = QuestionnaireQuestion.objects.create(
            questionnaire=questionnaire,
            text="本周出现了哪些表现？",
            q_type=choices.QuestionType.MULTIPLE,
            seq=2,
            is_required=True,
        )
        q1_opt = QuestionnaireOption.objects.create(
            question=q1,
            text="经常",
            score=Decimal("3.00"),
            seq=1,
        )
        q2_opt1 = QuestionnaireOption.objects.create(
            question=q2,
            text="心慌",
            score=Decimal("2.00"),
            seq=1,
        )
        q2_opt2 = QuestionnaireOption.objects.create(
            question=q2,
            text="手抖",
            score=Decimal("2.00"),
            seq=2,
        )

        submission = QuestionnaireSubmission.objects.create(
            patient=self.patient,
            questionnaire=questionnaire,
            total_score=Decimal("7.00"),
        )
        QuestionnaireAnswer.objects.create(submission=submission, question=q1, option=q1_opt)
        QuestionnaireAnswer.objects.create(
            submission=submission, question=q2, option=q2_opt1
        )
        QuestionnaireAnswer.objects.create(
            submission=submission, question=q2, option=q2_opt2
        )

        detail_url = reverse(
            "web_patient:questionnaire_submission_detail",
            kwargs={"submission_id": submission.id},
        )
        resp = self.client.get(detail_url, {"next": self.fallback_url})
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "web_patient/questionnaire_submission_detail.html")
        self.assertContains(resp, q1.text)
        self.assertContains(resp, q2.text)
        self.assertContains(resp, q1_opt.text)
        self.assertContains(resp, q2_opt1.text)
        self.assertContains(resp, q2_opt2.text)

    def test_questionnaire_submission_detail_redirects_next_for_unauthorized_submission(self):
        questionnaire = self._get_or_create_questionnaire()
        other_user = CustomUser.objects.create_user(
            username="other_patient_questionnaire_submission_detail",
            password="password",
            wx_openid="other_openid_questionnaire_submission_detail",
        )
        other_patient = PatientProfile.objects.create(
            user=other_user, name="Other Patient", phone="13800000022"
        )
        submission = QuestionnaireSubmission.objects.create(
            patient=other_patient,
            questionnaire=questionnaire,
            total_score=Decimal("2.00"),
        )

        next_url = f"{self.record_detail_url}?{urlencode({'type': 'anxiety', 'title': '焦虑评估', 'month': '2025-03'})}"
        detail_url = reverse(
            "web_patient:questionnaire_submission_detail",
            kwargs={"submission_id": submission.id},
        )
        resp = self.client.get(detail_url, {"next": next_url})
        self.assertEqual(resp.status_code, 302)
        parsed = urlsplit(resp["Location"])
        self.assertEqual(parsed.path, self.record_detail_url)
        query = parse_qs(parsed.query)
        self.assertEqual(query.get("type"), ["anxiety"])
        self.assertEqual(query.get("month"), ["2025-03"])

    def test_questionnaire_submission_detail_redirects_next_for_missing_submission(self):
        next_url = f"{self.record_detail_url}?{urlencode({'type': 'anxiety', 'title': '焦虑评估', 'month': '2025-03'})}"
        detail_url = reverse(
            "web_patient:questionnaire_submission_detail",
            kwargs={"submission_id": 999999},
        )
        resp = self.client.get(detail_url, {"next": next_url})
        self.assertEqual(resp.status_code, 302)
        parsed = urlsplit(resp["Location"])
        self.assertEqual(parsed.path, self.record_detail_url)
        query = parse_qs(parsed.query)
        self.assertEqual(query.get("type"), ["anxiety"])
        self.assertEqual(query.get("month"), ["2025-03"])
