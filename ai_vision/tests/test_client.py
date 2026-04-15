from unittest.mock import Mock, patch

import requests
from django.test import SimpleTestCase, override_settings

from ai_vision.exceptions import AiVisionConfigurationError, AiVisionResponseError
from ai_vision.services.client import (
    build_doubao_image_url_value,
    parse_json_text,
    request_doubao_report_json,
)


class AiVisionClientTests(SimpleTestCase):
    @override_settings(AI_VISION_IMAGE_BASE_URL="https://www.izencare.com")
    def test_build_doubao_image_url_value_prefixes_media_path(self):
        self.assertEqual(
            build_doubao_image_url_value("/media/reports/a.png"),
            "https://www.izencare.com/media/reports/a.png",
        )

    @override_settings(AI_VISION_IMAGE_BASE_URL="", WEB_BASE_URL="http://eric.dagimed.com")
    def test_build_doubao_image_url_value_falls_back_to_web_base_url(self):
        self.assertEqual(
            build_doubao_image_url_value("/media/reports/a.png"),
            "http://eric.dagimed.com/media/reports/a.png",
        )

    @override_settings(AI_VISION_IMAGE_BASE_URL="", WEB_BASE_URL="")
    def test_build_doubao_image_url_value_requires_base_url_for_media_path(self):
        with self.assertRaises(AiVisionConfigurationError):
            build_doubao_image_url_value("/media/reports/a.png")

    def test_build_doubao_image_url_value_keeps_absolute_url(self):
        self.assertEqual(
            build_doubao_image_url_value("https://img.test/a.png"),
            "https://img.test/a.png",
        )

    def test_parse_json_text_rejects_non_object(self):
        with self.assertRaises(AiVisionResponseError):
            parse_json_text("[]", source="测试模型")

    @override_settings(
        VOLCENGINE_KEY="test-key",
        VOLCENGINE_VISION_MODEL_ID="test-model",
        VOLCENGINE_BASE_URL="https://example.com/api/v3",
    )
    @patch("ai_vision.services.client.build_doubao_image_url_value", return_value="https://img.test/a.png")
    @patch("ai_vision.services.client.requests.post")
    def test_request_doubao_report_json_returns_json(self, mock_post, _mock_build_url):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "choices": [{"message": {"content": '{"is_medical_report": true, "items": []}'}}]
        }
        mock_post.return_value = response

        result = request_doubao_report_json(image_url="/media/x.png", prompt="hello")

        self.assertTrue(result["is_medical_report"])
        self.assertEqual(result["items"], [])

    @override_settings(
        VOLCENGINE_KEY="test-key",
        VOLCENGINE_VISION_MODEL_ID="test-model",
        VOLCENGINE_BASE_URL="https://example.com/api/v3",
    )
    @patch("ai_vision.services.client.build_doubao_image_url_value", return_value="https://img.test/a.png")
    @patch("ai_vision.services.client.requests.post")
    def test_request_doubao_report_json_raises_on_http_error(self, mock_post, _mock_build_url):
        response = Mock()
        response.status_code = 500
        response.text = "boom"
        response.raise_for_status.side_effect = requests.HTTPError("boom")
        mock_post.return_value = response

        with self.assertRaises(AiVisionResponseError):
            request_doubao_report_json(image_url="/media/x.png", prompt="hello")

    @override_settings(
        VOLCENGINE_KEY="test-key",
        VOLCENGINE_VISION_MODEL_ID="test-model",
        VOLCENGINE_BASE_URL="https://example.com/api/v3",
    )
    @patch("ai_vision.services.client.build_doubao_image_url_value", return_value="https://img.test/a.png")
    @patch("ai_vision.services.client.requests.post")
    def test_request_doubao_report_json_raises_on_non_json_text(self, mock_post, _mock_build_url):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"choices": [{"message": {"content": "not-json"}}]}
        mock_post.return_value = response

        with self.assertRaises(AiVisionResponseError):
            request_doubao_report_json(image_url="/media/x.png", prompt="hello")

    @override_settings(
        VOLCENGINE_KEY="test-key",
        VOLCENGINE_VISION_MODEL_ID="test-model",
        VOLCENGINE_BASE_URL="https://example.com/api/v3",
    )
    @patch("ai_vision.services.client.build_doubao_image_url_value", return_value="https://img.test/a.png")
    @patch("ai_vision.services.client.requests.post")
    def test_request_doubao_report_json_raises_on_invalid_top_level_shape(self, mock_post, _mock_build_url):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"choices": [{"message": {"content": "[]"}}]}
        mock_post.return_value = response

        with self.assertRaises(AiVisionResponseError):
            request_doubao_report_json(image_url="/media/x.png", prompt="hello")
