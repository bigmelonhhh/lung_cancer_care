from datetime import date
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from ai_vision.exceptions import AiVisionResponseError
from ai_vision.services import extract_report_image
from core.models import CheckupLibrary
from health_data.models import AIParseStatus, ReportImage, ReportUpload
from users.models import PatientProfile


@override_settings(VOLCENGINE_VISION_MODEL_ID="doubao-test-model")
class ExtractReportImageServiceTests(TestCase):
    def setUp(self):
        self.patient = PatientProfile.objects.create(phone="13900003000", name="AI患者")
        self.upload = ReportUpload.objects.create(patient=self.patient)
        self.blood = CheckupLibrary.objects.create(name="血生化", code="BIOCHEM_TEST", is_active=True)
        self.ct = CheckupLibrary.objects.create(name="胸部CT", code="CT_TEST", is_active=True)
        CheckupLibrary.objects.create(name="停用项目", code="INACTIVE_TEST", is_active=False)
        self.report_image = ReportImage.objects.create(
            upload=self.upload,
            image_url="https://example.com/report.png",
            record_type=ReportImage.RecordType.CHECKUP,
            checkup_item=self.blood,
            report_date=date(2026, 4, 15),
        )

    def test_missing_image_id_raises(self):
        with self.assertRaises(ReportImage.DoesNotExist):
            extract_report_image(999999)

    @patch("ai_vision.services.extractor.request_doubao_report_json")
    def test_extract_report_image_successfully_updates_fields(self, mock_request):
        mock_request.return_value = {
            "is_medical_report": True,
            "report_category": "血生化",
            "hospital_name": "协和",
            "patient_name": "张三",
            "patient_gender": "",
            "patient_age": "56岁",
            "sample_type": "血清",
            "report_name": "生化检验报告",
            "report_time_raw": "2026-04-15 08:00",
            "exam_time_raw": "",
            "items": [
                {
                    "item_name": "ALT",
                    "item_value": "42",
                    "abnormal_flag": "偏高",
                    "reference_low": "",
                    "reference_high": "40",
                    "unit": "U/L",
                    "item_code": "001",
                    "extra": "ignored",
                }
            ],
            "exam_findings": "",
            "doctor_interpretation": "",
            "ignored_top_level": "ignored",
        }

        payload = extract_report_image(self.report_image.id)
        self.report_image.refresh_from_db()

        self.assertEqual(self.report_image.ai_parse_status, AIParseStatus.SUCCESS)
        self.assertEqual(self.report_image.ai_model_name, "doubao-test-model")
        self.assertIsNotNone(self.report_image.ai_parsed_at)
        self.assertEqual(self.report_image.ai_error_message, "")
        self.assertEqual(payload["report_category"], "血生化")
        self.assertIsNone(payload["patient_gender"])
        self.assertEqual(payload["items"][0]["abnormal_flag"], "high")
        self.assertIsNone(payload["items"][0]["reference_low"])
        self.assertEqual(self.report_image.ai_structured_json, payload)

    @patch("ai_vision.services.extractor.request_doubao_report_json")
    def test_extract_report_image_keeps_non_medical_payload(self, mock_request):
        mock_request.return_value = {
            "is_medical_report": False,
            "report_category": "血生化",
            "items": None,
        }

        payload = extract_report_image(self.report_image.id)

        self.assertFalse(payload["is_medical_report"])
        self.assertEqual(payload["items"], [])
        self.assertIsNone(payload["report_category"])

    @patch("ai_vision.services.extractor.request_doubao_report_json")
    def test_extract_report_image_nulls_invalid_report_category(self, mock_request):
        mock_request.return_value = {
            "is_medical_report": True,
            "report_category": "风景照",
            "items": [],
        }

        payload = extract_report_image(self.report_image.id)

        self.assertIsNone(payload["report_category"])

    @patch("ai_vision.services.extractor.request_doubao_report_json")
    def test_extract_report_image_does_not_overwrite_existing_json_on_failure(self, mock_request):
        existing = {"is_medical_report": True, "report_category": "胸部CT", "items": []}
        self.report_image.ai_structured_json = existing
        self.report_image.save(update_fields=["ai_structured_json"])
        mock_request.side_effect = AiVisionResponseError("豆包失败")

        with self.assertRaises(AiVisionResponseError):
            extract_report_image(self.report_image.id)

        self.report_image.refresh_from_db()
        self.assertEqual(self.report_image.ai_parse_status, AIParseStatus.FAILED)
        self.assertEqual(self.report_image.ai_structured_json, existing)
        self.assertIn("豆包失败", self.report_image.ai_error_message)
        self.assertLessEqual(self.report_image.ai_parsed_at, timezone.now())
