import base64
from io import BytesIO
from unittest.mock import Mock, patch

import requests
from django.test import SimpleTestCase, override_settings

from ai_vision.exceptions import AiVisionResponseError
from ai_vision.services.client import (
    build_doubao_image_data_url,
    parse_json_text,
    request_doubao_report_json,
)


class AiVisionClientTests(SimpleTestCase):
    @patch("ai_vision.services.client.default_storage.open", return_value=BytesIO(b"\x89PNG\r\n\x1a\npng-data"))
    def test_build_doubao_image_data_url_reads_media_file_from_storage(self, mock_open):
        result = build_doubao_image_data_url("/media/reports/a.png")

        self.assertEqual(
            result,
            f"data:image/png;base64,{base64.b64encode(b'\x89PNG\r\n\x1a\npng-data').decode('ascii')}",
        )
        mock_open.assert_called_once_with("reports/a.png", "rb")

    @override_settings(AI_VISION_IMAGE_BASE_URL="", WEB_BASE_URL="https://zencare.imht.site")
    @patch("ai_vision.services.client.requests.get")
    @patch("ai_vision.services.client.default_storage.open", side_effect=OSError("missing"))
    def test_build_doubao_image_data_url_falls_back_to_server_side_fetch(self, _mock_open, mock_get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.content = b"\xff\xd8\xffjpeg-data"
        response.headers = {"Content-Type": "image/jpeg"}
        mock_get.return_value = response

        result = build_doubao_image_data_url("/media/reports/a.jpg")

        self.assertEqual(
            result,
            f"data:image/jpeg;base64,{base64.b64encode(b'\xff\xd8\xffjpeg-data').decode('ascii')}",
        )
        mock_get.assert_called_once_with(
            "https://zencare.imht.site/media/reports/a.jpg",
            timeout=30.0,
        )

    @patch("ai_vision.services.client.requests.get")
    def test_build_doubao_image_data_url_downloads_external_image_before_uploading(self, mock_get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.content = b"RIFF1234WEBPwebp-data"
        response.headers = {"Content-Type": "image/webp"}
        mock_get.return_value = response

        result = build_doubao_image_data_url("https://img.test/a.webp")

        self.assertEqual(
            result,
            f"data:image/webp;base64,{base64.b64encode(b'RIFF1234WEBPwebp-data').decode('ascii')}",
        )
        mock_get.assert_called_once_with("https://img.test/a.webp", timeout=30.0)

    def test_parse_json_text_rejects_non_object(self):
        with self.assertRaises(AiVisionResponseError):
            parse_json_text("[]", source="测试模型")

    @override_settings(
        VOLCENGINE_KEY="test-key",
        VOLCENGINE_VISION_MODEL_ID="test-model",
        VOLCENGINE_BASE_URL="https://example.com/api/v3",
    )
    @patch(
        "ai_vision.services.client.build_doubao_image_data_url",
        return_value="data:image/png;base64,ZmFrZS1pbWFnZQ==",
    )
    @patch("ai_vision.services.client.requests.post")
    def test_request_doubao_report_json_returns_json(self, mock_post, mock_build_data_url):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "choices": [{"message": {"content": '{"is_medical_report": true, "items": []}'}}]
        }
        mock_post.return_value = response

        result = request_doubao_report_json(image_url="/media/x.png", prompt="hello")

        self.assertTrue(result["is_medical_report"])
        self.assertEqual(result["items"], [])
        mock_build_data_url.assert_called_once_with("/media/x.png")
        self.assertEqual(
            mock_post.call_args.kwargs["json"]["messages"][0]["content"][1]["image_url"]["url"],
            "data:image/png;base64,ZmFrZS1pbWFnZQ==",
        )

    @override_settings(
        VOLCENGINE_KEY="test-key",
        VOLCENGINE_VISION_MODEL_ID="test-model",
        VOLCENGINE_BASE_URL="https://example.com/api/v3",
    )
    @patch(
        "ai_vision.services.client.build_doubao_image_data_url",
        return_value="data:image/png;base64,ZmFrZS1pbWFnZQ==",
    )
    @patch("ai_vision.services.client.requests.post")
    def test_request_doubao_report_json_raises_on_http_error(self, mock_post, _mock_build_data_url):
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
    @patch(
        "ai_vision.services.client.build_doubao_image_data_url",
        return_value="data:image/png;base64,ZmFrZS1pbWFnZQ==",
    )
    @patch("ai_vision.services.client.requests.post")
    def test_request_doubao_report_json_raises_on_non_json_text(self, mock_post, _mock_build_data_url):
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
    @patch(
        "ai_vision.services.client.build_doubao_image_data_url",
        return_value="data:image/png;base64,ZmFrZS1pbWFnZQ==",
    )
    @patch("ai_vision.services.client.requests.post")
    def test_request_doubao_report_json_raises_on_invalid_top_level_shape(self, mock_post, _mock_build_data_url):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"choices": [{"message": {"content": "[]"}}]}
        mock_post.return_value = response

        with self.assertRaises(AiVisionResponseError):
            request_doubao_report_json(image_url="/media/x.png", prompt="hello")
