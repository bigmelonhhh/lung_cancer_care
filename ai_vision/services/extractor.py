from __future__ import annotations

from django.conf import settings
from django.utils import timezone

from ai_vision.prompts.report_image import build_report_image_prompt
from ai_vision.schemas.report_image import sanitize_report_image_json
from ai_vision.services.client import request_doubao_report_json
from core.models import CheckupLibrary
from health_data.models import AIParseStatus, ReportImage


def _allowed_report_categories() -> list[str]:
    return list(
        CheckupLibrary.objects.filter(is_active=True).order_by("sort_order", "id").values_list("name", flat=True)
    )


def extract_report_image(image_id: int) -> dict:
    report_image = ReportImage.objects.select_related("upload", "checkup_item").get(pk=image_id)
    report_image.ai_parse_status = AIParseStatus.PENDING
    report_image.ai_error_message = ""
    report_image.save(update_fields=["ai_parse_status", "ai_error_message"])

    allowed_categories = _allowed_report_categories()
    try:
        raw_payload = request_doubao_report_json(
            image_url=report_image.image_url,
            prompt=build_report_image_prompt(allowed_categories=allowed_categories),
        )
        cleaned_payload = sanitize_report_image_json(
            raw_payload,
            allowed_categories=set(allowed_categories),
        )
        report_image.ai_parse_status = AIParseStatus.SUCCESS
        report_image.ai_structured_json = cleaned_payload
        report_image.ai_model_name = str(getattr(settings, "VOLCENGINE_VISION_MODEL_ID", "") or "")
        report_image.ai_parsed_at = timezone.now()
        report_image.ai_error_message = ""
        report_image.save(
            update_fields=[
                "ai_parse_status",
                "ai_structured_json",
                "ai_model_name",
                "ai_parsed_at",
                "ai_error_message",
            ]
        )
        return cleaned_payload
    except Exception as exc:
        report_image.ai_parse_status = AIParseStatus.FAILED
        report_image.ai_parsed_at = timezone.now()
        report_image.ai_error_message = str(exc).strip()[:1000]
        report_image.save(update_fields=["ai_parse_status", "ai_parsed_at", "ai_error_message"])
        raise
