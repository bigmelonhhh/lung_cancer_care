from datetime import date

from django.test import TestCase, Client
from django.urls import reverse

from core.models import CheckupLibrary
from health_data.models import ReportImage, UploadSource
from health_data.services.report_service import ReportUploadService
from users.models import CustomUser, PatientProfile


class ReviewRecordDetailTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = CustomUser.objects.create_user(
            username="testpatient_review_record_detail",
            password="password",
            wx_openid="test_openid_review_record_detail",
        )
        self.patient = PatientProfile.objects.create(
            user=self.user, name="Test Patient", phone="13900001001"
        )
        self.client.force_login(self.user)
        self.checkup_item = CheckupLibrary.objects.create(name="血常规", code="BLOOD_ROUTINE")

        self.page_url = reverse("web_patient:review_record_detail")
        self.api_url = reverse("web_patient:review_record_detail_data")

    def _create_report(self, report_date, image_suffix):
        ReportUploadService.create_upload(
            self.patient,
            images=[
                {
                    "image_url": f"https://example.com/{image_suffix}.png",
                    "record_type": ReportImage.RecordType.CHECKUP,
                    "checkup_item_id": self.checkup_item.id,
                    "report_date": report_date,
                }
            ],
            upload_source=UploadSource.CHECKUP_PLAN,
        )

    def test_review_record_detail_page_renders(self):
        response = self.client.get(
            self.page_url, {"title": "血常规", "category_code": self.checkup_item.code}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "血常规")
        self.assertContains(response, self.checkup_item.code)
        self.assertEqual(response.context["initial_groups"], [])
        self.assertEqual(response.context["batch_size"], 6)

    def test_review_record_detail_page_initial_batch_uses_six_groups_and_fills_previous_month(self):
        for day in (28, 18):
            self._create_report(date(2025, 3, day), f"2025-03-{day}")
        for day in (26, 22, 18, 12, 8):
            self._create_report(date(2025, 2, day), f"2025-02-{day}")

        response = self.client.get(
            self.page_url,
            {
                "title": "血常规",
                "category_code": self.checkup_item.code,
                "month": "2025-03",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["initial_groups"]), 6)
        self.assertEqual(
            [item["report_date"] for item in response.context["initial_groups"]],
            [
                "2025-03-28",
                "2025-03-18",
                "2025-02-26",
                "2025-02-22",
                "2025-02-18",
                "2025-02-12",
            ],
        )
        self.assertTrue(response.context["has_more"])
        self.assertEqual(response.context["next_cursor_month"], "2025-02")
        self.assertEqual(response.context["next_cursor_offset"], 4)

    def test_review_record_detail_page_empty_selected_month_still_backfills_history(self):
        for day in (20, 15, 10, 5):
            self._create_report(date(2025, 2, day), f"2025-02-{day}")
        for day in (29, 20, 11):
            self._create_report(date(2025, 1, day), f"2025-01-{day}")

        response = self.client.get(
            self.page_url,
            {
                "title": "血常规",
                "category_code": self.checkup_item.code,
                "month": "2025-03",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["initial_groups"]), 6)
        self.assertEqual(
            [item["report_date"] for item in response.context["initial_groups"]],
            [
                "2025-02-20",
                "2025-02-15",
                "2025-02-10",
                "2025-02-05",
                "2025-01-29",
                "2025-01-20",
            ],
        )
        self.assertTrue(response.context["has_more"])
        self.assertEqual(response.context["next_cursor_month"], "2025-01")
        self.assertEqual(response.context["next_cursor_offset"], 2)

    def test_review_record_detail_api_returns_grouped_payload(self):
        ReportUploadService.create_upload(
            self.patient,
            images=[
                {
                    "image_url": "https://example.com/nov-14-a.png",
                    "record_type": ReportImage.RecordType.CHECKUP,
                    "checkup_item_id": self.checkup_item.id,
                    "report_date": date(2025, 11, 14),
                },
                {
                    "image_url": "https://example.com/nov-14-b.png",
                    "record_type": ReportImage.RecordType.CHECKUP,
                    "checkup_item_id": self.checkup_item.id,
                    "report_date": date(2025, 11, 14),
                },
            ],
            upload_source=UploadSource.CHECKUP_PLAN,
        )

        response = self.client.get(
            self.api_url,
            {
                "patient_id": self.patient.id,
                "category_code": self.checkup_item.code,
                "report_month": "2025-11",
                "page_num": 1,
                "page_size": 10,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["list"][0]["report_date"], "2025-11-14")
        self.assertEqual(len(payload["list"][0]["image_urls"]), 2)

    def test_review_record_detail_api_cursor_pagination_loads_remaining_history(self):
        for day in (28, 18):
            self._create_report(date(2025, 3, day), f"2025-03-{day}")
        for day in (26, 22, 18, 12, 8):
            self._create_report(date(2025, 2, day), f"2025-02-{day}")

        response = self.client.get(
            self.api_url,
            {
                "patient_id": self.patient.id,
                "category_code": self.checkup_item.code,
                "month": "2025-03",
                "cursor_month": "2025-02",
                "cursor_offset": 4,
                "limit": 6,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual([item["report_date"] for item in payload["list"]], ["2025-02-08"])
        self.assertFalse(payload["has_more"])
        self.assertIsNone(payload["next_cursor_month"])
        self.assertIsNone(payload["next_cursor_offset"])
        self.assertEqual(payload["batch_size"], 6)

    def test_review_record_detail_api_rejects_patient_id_mismatch(self):
        other_user = CustomUser.objects.create_user(
            username="other_patient_review_record_detail",
            password="password",
            wx_openid="test_openid_other_review_record_detail",
        )
        other_patient = PatientProfile.objects.create(
            user=other_user, name="Other Patient", phone="13900001002"
        )

        response = self.client.get(
            self.api_url,
            {
                "patient_id": other_patient.id,
                "category_code": self.checkup_item.code,
                "report_month": "2025-11",
                "page_num": 1,
                "page_size": 10,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 403)

    def test_review_record_detail_api_empty_month_returns_zero(self):
        response = self.client.get(
            self.api_url,
            {
                "patient_id": self.patient.id,
                "category_code": self.checkup_item.code,
                "report_month": "2025-11",
                "page_num": 1,
                "page_size": 10,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["total"], 0)
        self.assertEqual(payload["list"], [])
