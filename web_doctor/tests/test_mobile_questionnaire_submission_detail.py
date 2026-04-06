from datetime import datetime
from decimal import Decimal
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

from django.contrib.auth import get_user_model
from django.test import TestCase
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
from users.models import DoctorProfile, PatientProfile

User = get_user_model()


class MobileQuestionnaireSubmissionDetailTests(TestCase):
    def setUp(self):
        self.doctor_user = User.objects.create_user(
            username="doc_questionnaire_detail",
            password="password",
            user_type=2,
            phone="13900139061",
        )
        self.doctor_profile = DoctorProfile.objects.create(
            user=self.doctor_user, name="Dr. Questionnaire Detail"
        )
        self.doctor_user.doctor_profile = self.doctor_profile
        self.doctor_user.save()

        self.patient = PatientProfile.objects.create(
            name="患者问卷A",
            phone="13800138261",
            doctor=self.doctor_profile,
        )
        self.other_patient = PatientProfile.objects.create(
            name="患者问卷B",
            phone="13800138262",
            doctor=self.doctor_profile,
        )

        self.client.force_login(self.doctor_user)
        self.record_detail_url = reverse("web_doctor:mobile_health_record_detail")
        self.health_records_url = reverse("web_doctor:mobile_health_records")
        self.mobile_patient_list_url = reverse("web_doctor:mobile_patient_list")
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

        with patch("web_doctor.views.mobile.health_record._is_member", return_value=True):
            resp = self.client.get(
                self.record_detail_url,
                {
                    "type": "anxiety",
                    "title": "焦虑评估",
                    "patient_id": self.patient.id,
                    "month": "2025-03",
                },
            )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, f'data-submission-id="{submission.id}"')
        self.assertContains(resp, 'role="button"')
        self.assertNotContains(resp, "查看详情")

        with patch("web_doctor.views.mobile.health_record._is_member", return_value=True):
            ajax_resp = self.client.get(
                self.record_detail_url,
                {
                    "type": "anxiety",
                    "title": "焦虑评估",
                    "patient_id": self.patient.id,
                    "month": "2025-03",
                },
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )
        self.assertEqual(ajax_resp.status_code, 200)
        payload = ajax_resp.json()
        self.assertTrue(payload["records"])
        self.assertEqual(payload["records"][0]["questionnaire_submission_id"], submission.id)

    def test_questionnaire_record_without_submission_id_shows_disabled_detail_button(self):
        self._get_or_create_questionnaire()
        HealthMetric.objects.create(
            patient=self.patient,
            metric_type=QuestionnaireCode.Q_ANXIETY,
            measured_at=self._aware_dt(),
            value_main=Decimal("3.00"),
            source="manual",
        )

        with patch("web_doctor.views.mobile.health_record._is_member", return_value=True):
            resp = self.client.get(
                self.record_detail_url,
                {
                    "type": "anxiety",
                    "title": "焦虑评估",
                    "patient_id": self.patient.id,
                    "month": "2025-03",
                },
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
        QuestionnaireAnswer.objects.create(submission=submission, question=q2, option=q2_opt1)
        QuestionnaireAnswer.objects.create(submission=submission, question=q2, option=q2_opt2)

        detail_url = reverse(
            "web_doctor:mobile_questionnaire_submission_detail",
            kwargs={"submission_id": submission.id},
        )
        next_url = (
            f"{self.record_detail_url}?"
            f"{urlencode({'type': 'anxiety', 'title': '焦虑评估', 'patient_id': self.patient.id, 'month': '2025-03'})}"
        )
        resp = self.client.get(detail_url, {"patient_id": self.patient.id, "next": next_url})
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "web_doctor/mobile/questionnaire_submission_detail.html")
        self.assertContains(resp, q1.text)
        self.assertContains(resp, q2.text)
        self.assertContains(resp, q1_opt.text)
        self.assertContains(resp, q2_opt1.text)
        self.assertContains(resp, q2_opt2.text)

    def test_questionnaire_submission_detail_redirects_next_for_unauthorized_submission(self):
        questionnaire = self._get_or_create_questionnaire()
        submission = QuestionnaireSubmission.objects.create(
            patient=self.other_patient,
            questionnaire=questionnaire,
            total_score=Decimal("2.00"),
        )

        next_url = (
            f"{self.record_detail_url}?"
            f"{urlencode({'type': 'anxiety', 'title': '焦虑评估', 'patient_id': self.patient.id, 'month': '2025-03'})}"
        )
        detail_url = reverse(
            "web_doctor:mobile_questionnaire_submission_detail",
            kwargs={"submission_id": submission.id},
        )
        resp = self.client.get(detail_url, {"patient_id": self.patient.id, "next": next_url})
        self.assertEqual(resp.status_code, 302)
        parsed = urlsplit(resp["Location"])
        self.assertEqual(parsed.path, self.record_detail_url)
        query = parse_qs(parsed.query)
        self.assertEqual(query.get("type"), ["anxiety"])
        self.assertEqual(query.get("month"), ["2025-03"])
        self.assertEqual(query.get("patient_id"), [str(self.patient.id)])

    def test_questionnaire_submission_detail_redirects_next_for_missing_submission(self):
        next_url = (
            f"{self.record_detail_url}?"
            f"{urlencode({'type': 'anxiety', 'title': '焦虑评估', 'patient_id': self.patient.id, 'month': '2025-03'})}"
        )
        detail_url = reverse(
            "web_doctor:mobile_questionnaire_submission_detail",
            kwargs={"submission_id": 999999},
        )
        resp = self.client.get(detail_url, {"patient_id": self.patient.id, "next": next_url})
        self.assertEqual(resp.status_code, 302)
        parsed = urlsplit(resp["Location"])
        self.assertEqual(parsed.path, self.record_detail_url)
        query = parse_qs(parsed.query)
        self.assertEqual(query.get("type"), ["anxiety"])
        self.assertEqual(query.get("month"), ["2025-03"])
        self.assertEqual(query.get("patient_id"), [str(self.patient.id)])

    def test_questionnaire_submission_detail_invalid_next_falls_back_to_health_records(self):
        detail_url = reverse(
            "web_doctor:mobile_questionnaire_submission_detail",
            kwargs={"submission_id": 999999},
        )
        resp = self.client.get(
            detail_url,
            {"patient_id": self.patient.id, "next": "https://evil.example.com/poc"},
        )
        self.assertEqual(resp.status_code, 302)
        parsed = urlsplit(resp["Location"])
        self.assertEqual(parsed.path, self.health_records_url)
        query = parse_qs(parsed.query)
        self.assertEqual(query.get("patient_id"), [str(self.patient.id)])

    def test_questionnaire_submission_detail_invalid_patient_falls_back_to_patient_list(self):
        detail_url = reverse(
            "web_doctor:mobile_questionnaire_submission_detail",
            kwargs={"submission_id": 999999},
        )
        resp = self.client.get(
            detail_url,
            {"patient_id": 999999, "next": "https://evil.example.com/poc"},
        )
        self.assertEqual(resp.status_code, 302)
        parsed = urlsplit(resp["Location"])
        self.assertEqual(parsed.path, self.mobile_patient_list_url)
