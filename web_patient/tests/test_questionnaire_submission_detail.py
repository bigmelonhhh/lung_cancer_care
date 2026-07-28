from datetime import datetime, timedelta
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
from market.models import Order, Product
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

    def test_dynamic_questionnaire_records_are_scoped_to_selected_service_package(self):
        product = Product.objects.create(
            name="问卷服务包",
            price=Decimal("199.00"),
            duration_days=30,
        )
        order = Order.objects.create(
            patient=self.patient,
            product=product,
            amount=Decimal("199.00"),
            status=Order.Status.PAID,
            paid_at=self._aware_dt(year=2025, month=3, day=1),
        )
        questionnaire = Questionnaire.objects.create(
            name='动态康复评估 <script>alert("x")</script>',
            code="Q_DYNAMIC_DETAIL",
            is_active=True,
        )
        in_range = QuestionnaireSubmission.objects.create(
            patient=self.patient,
            questionnaire=questionnaire,
            total_score=Decimal("8.00"),
        )
        out_of_range = QuestionnaireSubmission.objects.create(
            patient=self.patient,
            questionnaire=questionnaire,
            total_score=Decimal("2.00"),
        )
        QuestionnaireSubmission.objects.filter(pk=in_range.pk).update(
            created_at=timezone.make_aware(
                datetime.combine(order.start_date + timedelta(days=2), datetime.min.time()),
                self.tz,
            )
        )
        QuestionnaireSubmission.objects.filter(pk=out_of_range.pk).update(
            created_at=timezone.make_aware(
                datetime.combine(order.end_date + timedelta(days=2), datetime.min.time()),
                self.tz,
            )
        )

        with patch("web_patient.views.record._is_member", return_value=True):
            response = self.client.get(
                self.record_detail_url,
                {
                    "questionnaire_id": questionnaire.id,
                    "package_id": order.id,
                    "source": "survey_list",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["title"], questionnaire.name)
        self.assertEqual(response.context["questionnaire_id"], questionnaire.id)
        self.assertEqual(response.context["package_id"], order.id)
        self.assertEqual(len(response.context["records"]), 1)
        self.assertEqual(
            response.context["records"][0]["questionnaire_submission_id"],
            in_range.id,
        )
        self.assertEqual(response.context["records"][0]["score"], Decimal("8.00"))
        self.assertContains(response, f'data-submission-id="{in_range.id}"')
        self.assertNotContains(response, f'data-submission-id="{out_of_range.id}"')
        self.assertNotContains(response, '<script>alert("x")</script>')

    def test_dynamic_questionnaire_rejects_another_patients_package(self):
        product = Product.objects.create(
            name="其他患者服务包",
            price=Decimal("99.00"),
            duration_days=30,
        )
        other_patient = PatientProfile.objects.create(
            name="其他患者",
            phone="13800000029",
        )
        other_order = Order.objects.create(
            patient=other_patient,
            product=product,
            amount=Decimal("99.00"),
            status=Order.Status.PAID,
            paid_at=self._aware_dt(year=2025, month=3, day=1),
        )
        questionnaire = Questionnaire.objects.create(
            name="动态问卷",
            code="Q_DYNAMIC_PACKAGE_GUARD",
            is_active=True,
        )

        response = self.client.get(
            self.record_detail_url,
            {
                "questionnaire_id": questionnaire.id,
                "package_id": other_order.id,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 404)

    def test_dynamic_questionnaire_pagination_continues_to_previous_month(self):
        product = Product.objects.create(
            name="跨月问卷服务包",
            price=Decimal("299.00"),
            duration_days=90,
        )
        order = Order.objects.create(
            patient=self.patient,
            product=product,
            amount=Decimal("299.00"),
            status=Order.Status.PAID,
            paid_at=self._aware_dt(year=2025, month=1, day=1),
        )
        questionnaire = Questionnaire.objects.create(
            name="跨月动态问卷",
            code="Q_DYNAMIC_CROSS_MONTH",
            is_active=True,
        )
        february = QuestionnaireSubmission.objects.create(
            patient=self.patient,
            questionnaire=questionnaire,
            total_score=Decimal("2.00"),
        )
        march = QuestionnaireSubmission.objects.create(
            patient=self.patient,
            questionnaire=questionnaire,
            total_score=Decimal("6.00"),
        )
        QuestionnaireSubmission.objects.filter(pk=february.pk).update(
            created_at=self._aware_dt(year=2025, month=2, day=10)
        )
        QuestionnaireSubmission.objects.filter(pk=march.pk).update(
            created_at=self._aware_dt(year=2025, month=3, day=10)
        )

        first_page = self.client.get(
            self.record_detail_url,
            {
                "questionnaire_id": questionnaire.id,
                "package_id": order.id,
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
        self.assertEqual(first_page.context["next_cursor_offset"], 0)

        second_page = self.client.get(
            self.record_detail_url,
            {
                "questionnaire_id": questionnaire.id,
                "package_id": order.id,
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
