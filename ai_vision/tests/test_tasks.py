from unittest.mock import patch

from django.test import SimpleTestCase

from ai_vision.tasks import extract_report_image_task


class ExtractReportImageTaskTests(SimpleTestCase):
    @patch("ai_vision.tasks.extract_report_image")
    def test_task_calls_service(self, mock_extract):
        mock_extract.return_value = {"is_medical_report": True}

        payload = extract_report_image_task(12)

        mock_extract.assert_called_once_with(12)
        self.assertTrue(payload["is_medical_report"])

