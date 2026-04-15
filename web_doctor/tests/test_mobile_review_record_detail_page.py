from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import CheckupLibrary
from health_data.models import ReportImage, UploadSource
from health_data.services.report_service import ReportUploadService
from users.models import DoctorProfile, PatientProfile

User = get_user_model()


class MobileReviewRecordDetailPageTests(TestCase):
    def setUp(self):
        self.doctor_user = User.objects.create_user(
            username="doc_review_detail_page",
            password="password",
            user_type=2,
            phone="13900139061",
        )
        self.doctor_profile = DoctorProfile.objects.create(
            user=self.doctor_user, name="Dr. Review"
        )
        self.doctor_user.doctor_profile = self.doctor_profile
        self.doctor_user.save()

        self.patient = PatientProfile.objects.create(
            name="患者复查",
            phone="13800138261",
            doctor=self.doctor_profile,
        )
        self.checkup_item = CheckupLibrary.objects.create(name="胸部CT", code="ct")
        self.page_url = reverse("web_doctor:mobile_review_record_detail")
        self.api_url = reverse("web_doctor:mobile_review_record_detail_data")
        self.client.force_login(self.doctor_user)

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

    def test_review_record_detail_page_contains_core_ui_elements(self):
        response = self.client.get(
            f"{self.page_url}?patient_id={self.patient.id}&category_code=ct&title=复查详情"
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "web_doctor/mobile/review_record_detail.html")
        self.assertContains(response, "复查详情")
        self.assertContains(response, 'id="rrd-month-picker"')
        self.assertContains(response, 'id="rrd-scroll"')
        self.assertContains(response, f'data-patient-id="{self.patient.id}"')
        self.assertContains(response, 'id="rrd-virtual-inner"')
        self.assertEqual(response.context["initial_groups"], [])
        self.assertEqual(response.context["batch_size"], 6)

    def test_review_record_detail_page_initial_batch_matches_patient_side_cursor_logic(self):
        for day in (28, 18):
            self._create_report(date(2025, 3, day), f"2025-03-{day}")
        for day in (26, 22, 18, 12, 8):
            self._create_report(date(2025, 2, day), f"2025-02-{day}")

        response = self.client.get(
            self.page_url,
            {
                "patient_id": self.patient.id,
                "category_code": self.checkup_item.code,
                "title": "胸部CT",
                "month": "2025-03",
            },
        )

        self.assertEqual(response.status_code, 200)
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

    def test_review_record_detail_api_cursor_pagination_returns_remaining_history(self):
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
