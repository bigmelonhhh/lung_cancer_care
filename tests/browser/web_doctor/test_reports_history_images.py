import json

from django.test import tag

from core.models import CheckupLibrary
from health_data.models import ReportImage, ReportUpload, UploadSource
from tests.browser.web_doctor.base import DoctorBrowserTestCase, expect


@tag("browser")
class DoctorReportsHistoryImageArchiveBrowserTests(DoctorBrowserTestCase):
    def setUp(self):
        super().setUp()
        CheckupLibrary.objects.create(name="胸部CT", code="BROWSER_CT")
        self.upload = ReportUpload.objects.create(
            patient=self.patient,
            upload_source=UploadSource.PERSONAL_CENTER,
        )
        self.image = ReportImage.objects.create(
            upload=self.upload,
            image_url="/static/logo-192.png",
        )

    def _open_patient_reports(self):
        self.open_patient_workspace()
        self.page.locator("#tab-reports").click()
        expect(self.page.get_by_test_id("reports-history-content")).to_be_visible(timeout=10000)

    def _open_image_archives(self):
        self._open_patient_reports()
        self.page.get_by_test_id("reports-tab-images").click()
        expect(self.page.get_by_test_id("archive-filter-form")).to_be_visible(timeout=10000)
        expect(self.page.get_by_test_id("archive-image-card").first).to_be_visible(timeout=10000)

    def test_image_archive_tab_loads_in_real_browser(self):
        self._open_image_archives()

        expect(self.page.get_by_test_id("reports-history-content")).to_contain_text("上传日期")
        expect(self.page.get_by_test_id("archive-image-card")).to_have_count(1)

    def test_image_preview_opens_and_closes(self):
        self._open_image_archives()

        self.page.get_by_test_id("archive-image-card").click()
        overlay = self.page.locator('[data-testid="image-preview-overlay"]:visible').first
        expect(overlay).to_be_visible(timeout=10000)
        expect(overlay.locator("img")).to_have_attribute("src", "/static/logo-192.png")

        self.page.keyboard.press("Escape")
        expect(self.page.locator('[data-testid="image-preview-overlay"]:visible')).to_have_count(0, timeout=10000)

    def test_invalid_date_range_is_blocked_before_htmx_request(self):
        self._open_image_archives()

        requests = []
        self.page.on(
            "request",
            lambda request: requests.append(request.url)
            if "tab=images" in request.url and "fragment=content" in request.url
            else None,
        )

        self.page.get_by_test_id("archive-date-start").fill("2025-02-01")
        self.page.get_by_test_id("archive-date-end").fill("2025-01-01")

        dialog_messages = []

        def accept_dialog(dialog):
            dialog_messages.append(dialog.message)
            dialog.accept()

        self.page.once("dialog", accept_dialog)
        self.page.get_by_test_id("archive-filter-form").locator('button[type="submit"]').click()

        self.page.wait_for_timeout(300)
        self.assertEqual(dialog_messages, ["开始日期不能晚于结束日期"])
        self.assertEqual(requests, [])

    def test_archive_edit_submits_expected_payload(self):
        self._open_image_archives()

        self.page.get_by_test_id("archive-edit-submit-button").click()
        category = self.page.get_by_test_id("archive-category-select")
        report_date = self.page.get_by_test_id("archive-date-input")
        expect(category).to_be_visible(timeout=10000)
        expect(report_date).to_be_visible(timeout=10000)

        category.select_option("门诊")
        report_date.fill("2025-01-15")

        with self.page.expect_request(
            lambda request: request.method == "POST" and "/reports/batch-archive/" in request.url
        ) as request_info:
            self.page.get_by_test_id("archive-edit-submit-button").click()

        request = request_info.value
        payload = json.loads(request.post_data or "{}")
        self.assertEqual(
            payload,
            {
                "updates": [
                    {
                        "image_id": str(self.image.id),
                        "category": "门诊",
                        "report_date": "2025-01-15",
                    }
                ]
            },
        )
