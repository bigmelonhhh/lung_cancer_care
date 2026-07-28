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
from market.models import Order, Product
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
        self.tz = timezone.get_current_timezone()

        self.product = Product.objects.create(
            name="移动端问卷服务包",
            price=Decimal("199.00"),
            duration_days=90,
            is_active=True,
        )
        self.order = Order.objects.create(
            patient=self.patient,
            product=self.product,
            amount=Decimal("199.00"),
            status=Order.Status.PAID,
            paid_at=self._aware_dt(year=2025, month=1, day=1),
        )

        self.client.force_login(self.doctor_user)
        self.record_detail_url = reverse("web_doctor:mobile_health_record_detail")
        self.health_records_url = reverse("web_doctor:mobile_health_records")
        self.mobile_patient_list_url = reverse("web_doctor:mobile_patient_list")

    def _aware_dt(self, year=2025, month=3, day=10, hour=10, minute=0):
        return timezone.make_aware(datetime(year, month, day, hour, minute), self.tz)

    def _get_or_create_questionnaire(self):
        questionnaire, _ = Questionnaire.objects.get_or_create(
            code=QuestionnaireCode.Q_ANXIETY,
            defaults={"name": "焦虑评估", "is_active": True},
        )
        return questionnaire

    def _set_submission_time(self, submission, submitted_at):
        QuestionnaireSubmission.objects.filter(pk=submission.pk).update(
            created_at=submitted_at
        )
        submission.refresh_from_db()
        return submission

    def test_dynamic_questionnaire_detail_is_scoped_to_package_and_preserves_parameters(self):
        questionnaire = Questionnaire.objects.create(
            name='动态问卷 <script>alert("x")</script>',
            code="Q_MOBILE_DYNAMIC_DETAIL",
            is_active=True,
        )
        in_range = self._set_submission_time(
            QuestionnaireSubmission.objects.create(
                patient=self.patient,
                questionnaire=questionnaire,
                total_score=Decimal("8.00"),
            ),
            self._aware_dt(year=2025, month=3, day=10),
        )
        out_of_range = self._set_submission_time(
            QuestionnaireSubmission.objects.create(
                patient=self.patient,
                questionnaire=questionnaire,
                total_score=Decimal("2.00"),
            ),
            self._aware_dt(year=2024, month=12, day=20),
        )

        response = self.client.get(
            self.record_detail_url,
            {
                "patient_id": self.patient.id,
                "questionnaire_id": questionnaire.id,
                "package_id": self.order.id,
                "source": "survey_list",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["questionnaire_id"], questionnaire.id)
        self.assertEqual(response.context["package_id"], self.order.id)
        self.assertEqual(response.context["current_month"], "2025-03")
        self.assertEqual(
            [item["questionnaire_submission_id"] for item in response.context["records"]],
            [in_range.id],
        )
        self.assertContains(response, f'data-submission-id="{in_range.id}"')
        self.assertNotContains(response, f'data-submission-id="{out_of_range.id}"')
        self.assertContains(response, f'const questionnaireId = "{questionnaire.id}";')
        self.assertContains(response, f'const packageId = "{self.order.id}";')
        self.assertContains(response, "&questionnaire_id=${encodeURIComponent(questionnaireId)}")
        self.assertNotContains(response, '<script>alert("x")</script>')

    def test_dynamic_questionnaire_detail_paginates_across_package_months(self):
        questionnaire = Questionnaire.objects.create(
            name="跨月动态问卷",
            code="Q_MOBILE_DYNAMIC_CROSS_MONTH",
            is_active=True,
        )
        february = self._set_submission_time(
            QuestionnaireSubmission.objects.create(
                patient=self.patient,
                questionnaire=questionnaire,
                total_score=Decimal("2.00"),
            ),
            self._aware_dt(year=2025, month=2, day=10),
        )
        march = self._set_submission_time(
            QuestionnaireSubmission.objects.create(
                patient=self.patient,
                questionnaire=questionnaire,
                total_score=Decimal("6.00"),
            ),
            self._aware_dt(year=2025, month=3, day=10),
        )

        first_page = self.client.get(
            self.record_detail_url,
            {
                "patient_id": self.patient.id,
                "questionnaire_id": questionnaire.id,
                "package_id": self.order.id,
                "limit": 1,
            },
        )

        self.assertEqual(first_page.status_code, 200)
        self.assertEqual(
            [item["questionnaire_submission_id"] for item in first_page.context["records"]],
            [march.id],
        )
        self.assertTrue(first_page.context["has_more"])
        self.assertEqual(first_page.context["next_cursor_month"], "2025-02")

        second_page = self.client.get(
            self.record_detail_url,
            {
                "patient_id": self.patient.id,
                "questionnaire_id": questionnaire.id,
                "package_id": self.order.id,
                "month": "2025-03",
                "cursor_month": "2025-02",
                "cursor_offset": 0,
                "limit": 1,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(second_page.status_code, 200)
        self.assertEqual(
            [item["questionnaire_submission_id"] for item in second_page.json()["records"]],
            [february.id],
        )
        self.assertFalse(second_page.json()["has_more"])

    def test_dynamic_questionnaire_detail_rejects_another_patients_package(self):
        other_order = Order.objects.create(
            patient=self.other_patient,
            product=self.product,
            amount=Decimal("199.00"),
            status=Order.Status.PAID,
            paid_at=self._aware_dt(year=2025, month=1, day=1),
        )
        questionnaire = Questionnaire.objects.create(
            name="越权问卷",
            code="Q_MOBILE_DYNAMIC_FORBIDDEN",
            is_active=True,
        )

        response = self.client.get(
            self.record_detail_url,
            {
                "patient_id": self.patient.id,
                "questionnaire_id": questionnaire.id,
                "package_id": other_order.id,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 404)

    def test_dynamic_questionnaire_chart_uses_latest_submission_score_of_day(self):
        questionnaire = Questionnaire.objects.create(
            name="同日评分问卷",
            code="Q_MOBILE_DYNAMIC_LATEST",
            is_active=True,
        )
        self._set_submission_time(
            QuestionnaireSubmission.objects.create(
                patient=self.patient,
                questionnaire=questionnaire,
                total_score=Decimal("3.00"),
            ),
            self._aware_dt(year=2025, month=3, day=8, hour=9),
        )
        self._set_submission_time(
            QuestionnaireSubmission.objects.create(
                patient=self.patient,
                questionnaire=questionnaire,
                total_score=Decimal("9.00"),
            ),
            self._aware_dt(year=2025, month=3, day=8, hour=18),
        )

        response = self.client.get(
            self.record_detail_url,
            {
                "patient_id": self.patient.id,
                "questionnaire_id": questionnaire.id,
                "package_id": self.order.id,
                "month": "2025-03",
            },
        )

        self.assertEqual(response.status_code, 200)
        chart = response.context["chart_payload"]
        day_index = chart["dates"].index("03-08")
        self.assertEqual(chart["series"][0]["data"][day_index]["raw_value"], 9.0)

    def test_legacy_questionnaire_type_uses_dynamic_submission_detail(self):
        questionnaire = self._get_or_create_questionnaire()
        submission = self._set_submission_time(
            QuestionnaireSubmission.objects.create(
                patient=self.patient,
                questionnaire=questionnaire,
                total_score=Decimal("5.00"),
            ),
            self._aware_dt(year=2025, month=3, day=10),
        )

        with patch("web_doctor.views.mobile.health_record._is_member", return_value=True):
            response = self.client.get(
                self.record_detail_url,
                {
                    "type": "anxiety",
                    "title": "焦虑评估",
                    "patient_id": self.patient.id,
                    "month": "2025-03",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["questionnaire_id"], questionnaire.id)
        self.assertEqual(response.context["package_id"], self.order.id)
        self.assertEqual(
            response.context["records"][0]["questionnaire_submission_id"],
            submission.id,
        )

    def test_questionnaire_record_shows_detail_button_and_ajax_contains_submission_id(self):
        questionnaire = self._get_or_create_questionnaire()
        submission = self._set_submission_time(
            QuestionnaireSubmission.objects.create(
                patient=self.patient,
                questionnaire=questionnaire,
                total_score=Decimal("5.00"),
            ),
            self._aware_dt(),
        )

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

    def test_questionnaire_health_metric_without_submission_is_not_rendered(self):
        self._get_or_create_questionnaire()
        HealthMetric.objects.create(
            patient=self.patient,
            metric_type=QuestionnaireCode.Q_ANXIETY,
            measured_at=self._aware_dt(),
            value_main=Decimal("3.00"),
            source="manual",
        )

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
        self.assertEqual(resp.context["records"], [])
        self.assertNotContains(resp, 'class="record-item')
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
