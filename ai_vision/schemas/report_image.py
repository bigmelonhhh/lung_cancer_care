from __future__ import annotations

from copy import deepcopy
from typing import Any


TOP_LEVEL_KEYS = (
    "is_medical_report",
    "report_category",
    "hospital_name",
    "patient_name",
    "patient_gender",
    "patient_age",
    "sample_type",
    "report_name",
    "report_time_raw",
    "exam_time_raw",
    "items",
    "exam_findings",
    "doctor_interpretation",
)

ITEM_KEYS = (
    "item_name",
    "item_value",
    "abnormal_flag",
    "reference_low",
    "reference_high",
    "unit",
    "item_code",
)

EMPTY_REPORT_IMAGE_JSON: dict[str, Any] = {
    "is_medical_report": False,
    "report_category": None,
    "hospital_name": None,
    "patient_name": None,
    "patient_gender": None,
    "patient_age": None,
    "sample_type": None,
    "report_name": None,
    "report_time_raw": None,
    "exam_time_raw": None,
    "items": [],
    "exam_findings": None,
    "doctor_interpretation": None,
}

EMPTY_REPORT_ITEM_JSON: dict[str, Any] = {
    "item_name": None,
    "item_value": None,
    "abnormal_flag": None,
    "reference_low": None,
    "reference_high": None,
    "unit": None,
    "item_code": None,
}

ABNORMAL_FLAG_MAP = {
    "high": "high",
    "低": "low",
    "low": "low",
    "偏低": "low",
    "normal": "normal",
    "正常": "normal",
    "unknown": "unknown",
    "未知": "unknown",
    "高": "high",
    "偏高": "high",
    "h": "high",
    "l": "low",
    "n": "normal",
}


def build_empty_report_image_json() -> dict[str, Any]:
    return deepcopy(EMPTY_REPORT_IMAGE_JSON)


def normalize_boolean(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n", ""}:
            return False
    if value is None:
        return False
    return bool(value)


def normalize_scalar(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return value


def normalize_abnormal_flag(value: Any) -> str | None:
    normalized = normalize_scalar(value)
    if normalized is None:
        return None
    return ABNORMAL_FLAG_MAP.get(str(normalized).strip().lower(), "unknown")


def sanitize_item(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        item = {}
    cleaned = deepcopy(EMPTY_REPORT_ITEM_JSON)
    for key in ITEM_KEYS:
        value = item.get(key)
        if key == "abnormal_flag":
            cleaned[key] = normalize_abnormal_flag(value)
        else:
            cleaned[key] = normalize_scalar(value)
    return cleaned


def sanitize_report_image_json(payload: Any, *, allowed_categories: set[str]) -> dict[str, Any]:
    cleaned = build_empty_report_image_json()
    if not isinstance(payload, dict):
        payload = {}

    for key in TOP_LEVEL_KEYS:
        if key == "items":
            continue
        if key == "is_medical_report":
            cleaned[key] = normalize_boolean(payload.get(key))
            continue
        cleaned[key] = normalize_scalar(payload.get(key))

    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raw_items = []
    cleaned["items"] = [sanitize_item(item) for item in raw_items]

    category = cleaned["report_category"]
    if category not in allowed_categories:
        cleaned["report_category"] = None

    if not cleaned["is_medical_report"]:
        for key in TOP_LEVEL_KEYS:
            if key == "is_medical_report":
                continue
            if key == "items":
                cleaned[key] = []
            else:
                cleaned[key] = None

    return cleaned
