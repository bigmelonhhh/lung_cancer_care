"""Services for structured checkup result storage and orphan reprocessing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import logging
import re
from typing import Any, Iterable

from django.db import transaction
from django.utils import timezone

from core.models import CheckupFieldMapping, StandardField, StandardFieldAlias, StandardFieldValueType
from core.utils.normalization import normalize_standard_field_name
from health_data.models import (
    CheckupOrphanField,
    CheckupResultAbnormalFlag,
    CheckupResultSourceType,
    CheckupResultValue,
    OrphanFieldStatus,
    ReportImage,
)

logger = logging.getLogger(__name__)

WARNING_STATUS_PENDING = "pending"
WARNING_STATUS_IGNORED = "ignored"
WARNING_STATUS_RESOLVED = "resolved"

REPORT_CATEGORY_CONFLICT = "report_category_conflict"
REPORT_DATE_CONFLICT = "report_date_conflict"
MATCH_STATUS_MATCHED = "matched"
MATCH_STATUS_ORPHAN = "orphan"
MATCH_STATUS_EMPTY = "empty"

ORPHAN_REASON_MISSING_ALIAS = "未命中标准字段别名"
ORPHAN_REASON_MISSING_MAPPING = "检查项未配置标准字段映射"
ORPHAN_REASON_INVALID_DECIMAL = "数值解析失败"
ORPHAN_REASON_EMPTY_NAME = "项目名为空"

DATE_TEXT_PATTERN = re.compile(
    r"(?P<year>\d{4})\s*[./\-年]\s*(?P<month>\d{1,2})\s*[./\-月]\s*(?P<day>\d{1,2})\s*日?"
)


@dataclass
class StructuredRowPayload:
    """Normalized row payload for ingestion."""

    raw_name: str
    raw_value: str
    item_code: str = ""
    unit: str = ""
    lower_bound: Decimal | None = None
    upper_bound: Decimal | None = None
    range_text: str = ""
    raw_line_text: str = ""


def _format_decimal_display(value: Decimal | None) -> str:
    if value is None:
        return "-"
    normalized = value.normalize()
    display = format(normalized, "f")
    if "." in display:
        display = display.rstrip("0").rstrip(".")
    return display or "0"


def _format_result_value(result_value: CheckupResultValue | None) -> str:
    if result_value is None:
        return "-"
    raw_value = (result_value.raw_value or "").strip()
    if raw_value:
        return raw_value
    if result_value.value_text:
        return result_value.value_text
    if result_value.value_numeric is not None:
        return _format_decimal_display(result_value.value_numeric)
    return "-"


def _format_reference_range(result_value: CheckupResultValue) -> str:
    if result_value.range_text:
        return result_value.range_text
    lower = _format_decimal_display(result_value.lower_bound) if result_value.lower_bound is not None else ""
    upper = _format_decimal_display(result_value.upper_bound) if result_value.upper_bound is not None else ""
    if lower and upper:
        return f"{lower}-{upper}"
    if lower:
        return f">={lower}"
    if upper:
        return f"<={upper}"
    return "-"


def build_report_image_metrics_payload(report_image: ReportImage) -> dict[str, Any]:
    """Build doctor-side metrics panel payload for one report image."""

    title = "复查指标"
    if report_image.checkup_item_id and getattr(report_image.checkup_item, "name", ""):
        title = f"复查-{report_image.checkup_item.name}"

    result_values = list(
        CheckupResultValue.objects.filter(report_image=report_image)
        .select_related("standard_field")
        .order_by("id")
    )
    if not result_values:
        return {
            "status": "success",
            "title": title,
            "report_date": report_image.report_date.isoformat() if report_image.report_date else "",
            "image_id": report_image.id,
            "rows": [],
            "empty_message": "该图片暂无已匹配指标数据",
        }

    mapping_order_map: dict[int, int] = {}
    if report_image.checkup_item_id:
        mapping_order_map = dict(
            CheckupFieldMapping.objects.filter(
                checkup_item_id=report_image.checkup_item_id,
                is_active=True,
            ).values_list("standard_field_id", "sort_order")
        )

    current_date = _resolve_report_date(report_image)
    previous_map: dict[int, CheckupResultValue] = {}
    previous_values = (
        CheckupResultValue.objects.filter(
            patient_id=report_image.upload.patient_id,
            standard_field_id__in={item.standard_field_id for item in result_values},
            report_date__lt=current_date,
        )
        .select_related("standard_field")
        .order_by("standard_field_id", "-report_date", "-id")
    )
    for previous in previous_values:
        previous_map.setdefault(previous.standard_field_id, previous)

    sorted_results = sorted(
        result_values,
        key=lambda item: (
            mapping_order_map.get(item.standard_field_id, 10**9),
            item.standard_field.local_code or "",
            item.standard_field_id,
            item.id,
        ),
    )

    rows: list[dict[str, Any]] = []
    for current in sorted_results:
        previous = previous_map.get(current.standard_field_id)
        value_type = current.standard_field.value_type
        delta_display = "-"
        delta_direction = "none"
        if (
            value_type == StandardFieldValueType.DECIMAL
            and current.value_numeric is not None
            and previous is not None
            and previous.value_numeric is not None
        ):
            delta = current.value_numeric - previous.value_numeric
            delta_direction = "up" if delta > 0 else "down" if delta < 0 else "none"
            delta_display = _format_decimal_display(delta)
            if delta > 0:
                delta_display = f"+{delta_display}"

        rows.append(
            {
                "field_code": current.standard_field.local_code or "-",
                "field_name": current.standard_field.chinese_name or current.standard_field.english_abbr or "-",
                "current_value_display": _format_result_value(current),
                "unit": current.unit or current.standard_field.default_unit or "-",
                "reference_range": _format_reference_range(current),
                "previous_value_display": _format_result_value(previous),
                "delta_display": delta_display,
                "delta_direction": delta_direction,
                "abnormal_flag": current.abnormal_flag,
            }
        )

    return {
        "status": "success",
        "title": title,
        "report_date": current_date.isoformat(),
        "image_id": report_image.id,
        "rows": rows,
        "empty_message": "",
    }


def _coerce_decimal(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None


def _resolve_report_date(report_image: ReportImage) -> date:
    if report_image.report_date:
        return report_image.report_date
    if report_image.upload_id and report_image.upload.created_at:
        return timezone.localtime(report_image.upload.created_at).date()
    return timezone.localdate()


def _infer_abnormal_flag(
    *,
    value_numeric: Decimal | None,
    lower_bound: Decimal | None,
    upper_bound: Decimal | None,
) -> str:
    if value_numeric is None:
        return CheckupResultAbnormalFlag.UNKNOWN
    if lower_bound is not None and value_numeric < lower_bound:
        return CheckupResultAbnormalFlag.LOW
    if upper_bound is not None and value_numeric > upper_bound:
        return CheckupResultAbnormalFlag.HIGH
    if lower_bound is not None or upper_bound is not None:
        return CheckupResultAbnormalFlag.NORMAL
    return CheckupResultAbnormalFlag.UNKNOWN


def _build_orphan_defaults(
    *,
    patient_id: int,
    report_image: ReportImage,
    checkup_item_id: int,
    report_date: date,
    row: StructuredRowPayload,
    note: str = "",
) -> dict:
    numeric_value = _coerce_decimal(row.raw_value)
    return {
        "patient_id": patient_id,
        "checkup_item_id": checkup_item_id,
        "report_date": report_date,
        "raw_name": row.raw_name,
        "raw_value": row.raw_value,
        "item_code": row.item_code,
        "value_numeric": numeric_value,
        "value_text": row.raw_value if numeric_value is None else "",
        "unit": row.unit,
        "lower_bound": row.lower_bound,
        "upper_bound": row.upper_bound,
        "range_text": row.range_text,
        "raw_line_text": row.raw_line_text,
        "status": OrphanFieldStatus.PENDING,
        "resolved_standard_field": None,
        "resolved_result_value": None,
        "resolved_at": None,
        "notes": note,
    }


def _upsert_result_value(
    *,
    report_image: ReportImage,
    patient_id: int,
    checkup_item_id: int,
    report_date: date,
    standard_field: StandardField,
    raw_name: str,
    raw_value: str,
    item_code: str,
    unit: str,
    lower_bound: Decimal | None,
    upper_bound: Decimal | None,
    range_text: str,
    source_type: str,
) -> CheckupResultValue:
    normalized_name = normalize_standard_field_name(raw_name)
    defaults = {
        "patient_id": patient_id,
        "checkup_item_id": checkup_item_id,
        "report_date": report_date,
        "raw_name": raw_name,
        "normalized_name": normalized_name,
        "raw_value": raw_value,
        "item_code": item_code,
        "unit": unit,
        "lower_bound": lower_bound,
        "upper_bound": upper_bound,
        "range_text": range_text,
        "source_type": source_type,
    }

    if standard_field.value_type == StandardFieldValueType.TEXT:
        defaults["value_text"] = raw_value
        defaults["value_numeric"] = None
        defaults["abnormal_flag"] = CheckupResultAbnormalFlag.UNKNOWN
    else:
        value_numeric = _coerce_decimal(raw_value)
        defaults["value_numeric"] = value_numeric
        defaults["value_text"] = ""
        defaults["abnormal_flag"] = _infer_abnormal_flag(
            value_numeric=value_numeric,
            lower_bound=lower_bound,
            upper_bound=upper_bound,
        )

    result_value, _ = CheckupResultValue.objects.update_or_create(
        report_image=report_image,
        standard_field=standard_field,
        defaults=defaults,
    )
    return result_value


def _parse_report_date_text(text: str | None) -> date | None:
    if not text:
        return None
    match = DATE_TEXT_PATTERN.search(str(text).strip())
    if not match:
        return None
    try:
        return date(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
        )
    except ValueError:
        return None


def _build_warning(message: str, *, details: dict, status: str = WARNING_STATUS_PENDING) -> dict:
    return {
        "status": status,
        "message": message,
        "details": details,
    }


def _normalize_warning_keys(keys: Iterable[str] | None) -> set[str]:
    return {
        str(key).strip()
        for key in (keys or [])
        if str(key).strip()
    }


def ignore_ai_sync_warnings(report_image: ReportImage, warning_keys: Iterable[str] | None = None) -> dict:
    warnings = dict(report_image.ai_sync_warnings or {})
    selected_keys = _normalize_warning_keys(warning_keys) or set(warnings.keys())
    changed = False

    for key in selected_keys:
        warning = warnings.get(key)
        if not isinstance(warning, dict):
            continue
        if warning.get("status") == WARNING_STATUS_IGNORED:
            continue
        warning["status"] = WARNING_STATUS_IGNORED
        warnings[key] = warning
        changed = True

    if changed:
        report_image.ai_sync_warnings = warnings
        report_image.save(update_fields=["ai_sync_warnings"])
    return warnings


def _get_effective_payload(report_image: ReportImage) -> dict[str, Any]:
    payload = report_image.get_effective_structured_json()
    return payload if isinstance(payload, dict) else {}


def _current_source_type(report_image: ReportImage) -> str:
    if report_image.get_effective_structured_json_source() == "REVIEWED":
        return CheckupResultSourceType.MANUAL
    return CheckupResultSourceType.AI


def _clear_report_image_structured_data(report_image: ReportImage) -> None:
    CheckupResultValue.objects.filter(report_image=report_image).delete()
    CheckupOrphanField.objects.filter(report_image=report_image).delete()


def _build_rows_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        return []

    rows: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        item_name = str(item.get("item_name") or "").strip()
        if not item_name:
            continue
        low = item.get("reference_low")
        high = item.get("reference_high")
        range_text = ""
        if low not in (None, "") and high not in (None, ""):
            range_text = f"{str(low).strip()}-{str(high).strip()}"
        rows.append(
            {
                "name": item_name,
                "value": str(item.get("item_value") or "").strip(),
                "item_code": str(item.get("item_code") or "").strip(),
                "unit": str(item.get("unit") or "").strip(),
                "lower_bound": low,
                "upper_bound": high,
                "range_text": range_text,
            }
        )
    return rows


def analyze_report_image_structured_items(report_image: ReportImage) -> list[dict[str, Any]]:
    payload = _get_effective_payload(report_image)
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        return []
    if not report_image.checkup_item_id:
        return []

    normalized_names: set[str] = set()
    parsed_rows: list[tuple[int, dict[str, Any], str]] = []
    for index, item in enumerate(raw_items):
        if not isinstance(item, dict):
            parsed_rows.append((index, {}, ""))
            continue
        item_name = str(item.get("item_name") or "").strip()
        parsed_rows.append((index, item, item_name))
        if item_name:
            normalized_names.add(normalize_standard_field_name(item_name))

    aliases = {
        alias.normalized_name: alias
        for alias in StandardFieldAlias.objects.select_related("standard_field").filter(
            normalized_name__in=normalized_names,
            is_active=True,
            standard_field__is_active=True,
        )
    }
    mapped_field_ids = set(
        CheckupFieldMapping.objects.filter(
            checkup_item_id=report_image.checkup_item_id,
            is_active=True,
            standard_field__is_active=True,
        ).values_list("standard_field_id", flat=True)
    )

    analysis_rows: list[dict[str, Any]] = []
    for index, item, item_name in parsed_rows:
        if not item_name:
            analysis_rows.append(
                {
                    "index": index,
                    "status": MATCH_STATUS_EMPTY,
                    "status_label": "待补充",
                    "is_orphan": False,
                    "reason": ORPHAN_REASON_EMPTY_NAME,
                    "suggestion": "补充项目名或删除该行。",
                    "standard_field_display": "",
                }
            )
            continue

        normalized_name = normalize_standard_field_name(item_name)
        alias = aliases.get(normalized_name)
        if alias is None:
            analysis_rows.append(
                {
                    "index": index,
                    "status": MATCH_STATUS_ORPHAN,
                    "status_label": "孤儿字段",
                    "is_orphan": True,
                    "reason": ORPHAN_REASON_MISSING_ALIAS,
                    "suggestion": "补别名库或修正项目名。",
                    "standard_field_display": "",
                }
            )
            continue

        standard_field = alias.standard_field
        standard_field_display = (
            standard_field.chinese_name
            or standard_field.local_code
            or str(standard_field.pk)
        )
        if standard_field.id not in mapped_field_ids:
            analysis_rows.append(
                {
                    "index": index,
                    "status": MATCH_STATUS_ORPHAN,
                    "status_label": "孤儿字段",
                    "is_orphan": True,
                    "reason": ORPHAN_REASON_MISSING_MAPPING,
                    "suggestion": "补检查项映射。",
                    "standard_field_display": standard_field_display,
                }
            )
            continue

        item_value = str(item.get("item_value") or "").strip()
        if (
            standard_field.value_type == StandardFieldValueType.DECIMAL
            and item_value
            and _coerce_decimal(item_value) is None
        ):
            analysis_rows.append(
                {
                    "index": index,
                    "status": MATCH_STATUS_ORPHAN,
                    "status_label": "孤儿字段",
                    "is_orphan": True,
                    "reason": ORPHAN_REASON_INVALID_DECIMAL,
                    "suggestion": "修正识别值、单位或数值格式。",
                    "standard_field_display": standard_field_display,
                }
            )
            continue

        analysis_rows.append(
            {
                "index": index,
                "status": MATCH_STATUS_MATCHED,
                "status_label": "已关联标准字段",
                "is_orphan": False,
                "reason": "",
                "suggestion": "",
                "standard_field_display": standard_field_display,
            }
        )
    return analysis_rows


def _sync_payload_warnings(report_image: ReportImage, payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    warnings = dict(report_image.ai_sync_warnings or {})
    changed = False
    blocking_keys: list[str] = []
    current_category = (report_image.checkup_item.name or "").strip()
    ai_category = str(payload.get("report_category") or "").strip()

    if ai_category:
        existing = warnings.get(REPORT_CATEGORY_CONFLICT)
        if ai_category != current_category:
            status = WARNING_STATUS_PENDING
            if isinstance(existing, dict) and existing.get("status") == WARNING_STATUS_IGNORED:
                status = WARNING_STATUS_IGNORED
            warning = _build_warning(
                "AI识别的报告分类与当前归档分类不一致。",
                details={
                    "image_checkup_item": current_category,
                    "ai_report_category": ai_category,
                },
                status=status,
            )
            if warnings.get(REPORT_CATEGORY_CONFLICT) != warning:
                warnings[REPORT_CATEGORY_CONFLICT] = warning
                changed = True
            if status == WARNING_STATUS_PENDING:
                blocking_keys.append(REPORT_CATEGORY_CONFLICT)
        elif isinstance(existing, dict) and existing.get("status") != WARNING_STATUS_RESOLVED:
            warnings[REPORT_CATEGORY_CONFLICT] = _build_warning(
                "AI识别的报告分类已与当前归档分类一致。",
                details={
                    "image_checkup_item": current_category,
                    "ai_report_category": ai_category,
                },
                status=WARNING_STATUS_RESOLVED,
            )
            changed = True

    ai_report_date = _parse_report_date_text(payload.get("report_time_raw"))
    existing_date_warning = warnings.get(REPORT_DATE_CONFLICT)
    if report_image.report_date and ai_report_date and ai_report_date != report_image.report_date:
        status = WARNING_STATUS_PENDING
        if isinstance(existing_date_warning, dict) and existing_date_warning.get("status") == WARNING_STATUS_IGNORED:
            status = WARNING_STATUS_IGNORED
        warning = _build_warning(
            "AI识别的报告日期与当前归档日期不一致。",
            details={
                "image_report_date": report_image.report_date.isoformat(),
                "ai_report_time_raw": payload.get("report_time_raw"),
                "parsed_ai_report_date": ai_report_date.isoformat(),
            },
            status=status,
        )
        if warnings.get(REPORT_DATE_CONFLICT) != warning:
            warnings[REPORT_DATE_CONFLICT] = warning
            changed = True
        if status == WARNING_STATUS_PENDING:
            blocking_keys.append(REPORT_DATE_CONFLICT)
    elif (
        report_image.report_date
        and ai_report_date
        and isinstance(existing_date_warning, dict)
        and existing_date_warning.get("status") != WARNING_STATUS_RESOLVED
    ):
        warnings[REPORT_DATE_CONFLICT] = _build_warning(
            "AI识别的报告日期已与当前归档日期一致。",
            details={
                "image_report_date": report_image.report_date.isoformat(),
                "ai_report_time_raw": payload.get("report_time_raw"),
                "parsed_ai_report_date": ai_report_date.isoformat(),
            },
            status=WARNING_STATUS_RESOLVED,
        )
        changed = True

    if changed:
        report_image.ai_sync_warnings = warnings
        report_image.save(update_fields=["ai_sync_warnings"])
    return warnings, blocking_keys


@transaction.atomic
def rebuild_report_image_structured_results(report_image: ReportImage) -> dict[str, object]:
    payload = _get_effective_payload(report_image)
    if (
        report_image.get_effective_structured_json_source() != "REVIEWED"
        and report_image.ai_parse_status != "SUCCESS"
    ):
        return {"status": "skipped", "reason": "ai_not_ready"}
    if not payload:
        return {"status": "skipped", "reason": "missing_payload"}
    if not report_image.checkup_item_id:
        return {"status": "skipped", "reason": "missing_checkup_item"}
    if not payload.get("is_medical_report"):
        _clear_report_image_structured_data(report_image)
        if report_image.ai_sync_warnings:
            report_image.ai_sync_warnings = {}
            report_image.save(update_fields=["ai_sync_warnings"])
        return {
            "status": "synced",
            "created_or_updated": 0,
            "orphans": 0,
            "warnings": {},
        }

    warnings, blocking_keys = _sync_payload_warnings(report_image, payload)

    if blocking_keys:
        return {
            "status": "warning_blocked",
            "warnings": {key: warnings[key] for key in blocking_keys},
        }

    if not str(payload.get("report_category") or "").strip():
        return {"status": "skipped", "reason": "missing_report_category", "warnings": warnings}

    rows = _build_rows_from_payload(payload)
    _clear_report_image_structured_data(report_image)
    if not rows:
        return {
            "status": "synced",
            "created_or_updated": 0,
            "orphans": 0,
            "warnings": warnings,
        }

    stats = ingest_structured_checkup_rows(
        report_image=report_image,
        rows=rows,
        source_type=_current_source_type(report_image),
    )
    return {
        "status": "synced",
        "created_or_updated": stats["created_or_updated"],
        "orphans": stats["orphans"],
        "warnings": warnings,
    }


def sync_lab_results_from_ai_json(report_image: ReportImage) -> dict[str, object]:
    return rebuild_report_image_structured_results(report_image)


@transaction.atomic
def ingest_structured_checkup_rows(
    *,
    report_image: ReportImage,
    rows: Iterable[dict],
    source_type: str = CheckupResultSourceType.AI,
) -> dict[str, int]:
    """
    Ingest structured rows for one report image.

    Rows are dictionaries with at least:
    - name/raw_name
    - value/raw_value
    Optional:
    - unit
    - lower_bound
    - upper_bound
    - range_text
    - raw_line_text
    """

    if not report_image.checkup_item_id:
        raise ValueError("report_image.checkup_item is required for structured result ingestion")

    patient_id = report_image.upload.patient_id
    checkup_item_id = report_image.checkup_item_id
    report_date = _resolve_report_date(report_image)
    stats = {"created_or_updated": 0, "orphans": 0}

    normalized_names: set[str] = set()
    normalized_rows: list[StructuredRowPayload] = []
    for item in rows:
        raw_name = str(item.get("raw_name") or item.get("name") or "").strip()
        if not raw_name:
            continue
        payload = StructuredRowPayload(
            raw_name=raw_name,
            raw_value=str(item.get("raw_value") if item.get("raw_value") is not None else item.get("value") or "").strip(),
            item_code=str(item.get("item_code") or "").strip(),
            unit=str(item.get("unit") or "").strip(),
            lower_bound=_coerce_decimal(item.get("lower_bound")),
            upper_bound=_coerce_decimal(item.get("upper_bound")),
            range_text=str(item.get("range_text") or "").strip(),
            raw_line_text=str(item.get("raw_line_text") or "").strip(),
        )
        normalized_rows.append(payload)
        normalized_names.add(normalize_standard_field_name(payload.raw_name))

    aliases = {
        alias.normalized_name: alias
        for alias in StandardFieldAlias.objects.select_related("standard_field").filter(
            normalized_name__in=normalized_names,
            is_active=True,
            standard_field__is_active=True,
        )
    }
    mapped_field_ids = set(
        CheckupFieldMapping.objects.filter(
            checkup_item_id=checkup_item_id,
            is_active=True,
            standard_field__is_active=True,
        ).values_list("standard_field_id", flat=True)
    )

    for row in normalized_rows:
        normalized_name = normalize_standard_field_name(row.raw_name)
        alias = aliases.get(normalized_name)
        if alias is None:
            CheckupOrphanField.objects.update_or_create(
                report_image=report_image,
                normalized_name=normalized_name,
                defaults=_build_orphan_defaults(
                    patient_id=patient_id,
                    report_image=report_image,
                    checkup_item_id=checkup_item_id,
                    report_date=report_date,
                    row=row,
                    note="未命中标准字段别名。",
                ),
            )
            stats["orphans"] += 1
            continue

        standard_field = alias.standard_field
        if standard_field.id not in mapped_field_ids:
            CheckupOrphanField.objects.update_or_create(
                report_image=report_image,
                normalized_name=normalized_name,
                defaults=_build_orphan_defaults(
                    patient_id=patient_id,
                    report_image=report_image,
                    checkup_item_id=checkup_item_id,
                    report_date=report_date,
                    row=row,
                    note="命中别名但检查项未配置该标准字段映射。",
                ),
            )
            stats["orphans"] += 1
            continue

        if (
            standard_field.value_type == StandardFieldValueType.DECIMAL
            and row.raw_value
            and _coerce_decimal(row.raw_value) is None
        ):
            CheckupOrphanField.objects.update_or_create(
                report_image=report_image,
                normalized_name=normalized_name,
                defaults=_build_orphan_defaults(
                    patient_id=patient_id,
                    report_image=report_image,
                    checkup_item_id=checkup_item_id,
                    report_date=report_date,
                    row=row,
                    note="命中别名但数值解析失败。",
                ),
            )
            stats["orphans"] += 1
            continue

        _upsert_result_value(
            report_image=report_image,
            patient_id=patient_id,
            checkup_item_id=checkup_item_id,
            report_date=report_date,
            standard_field=standard_field,
            raw_name=row.raw_name,
            raw_value=row.raw_value,
            item_code=row.item_code,
            unit=row.unit,
            lower_bound=row.lower_bound,
            upper_bound=row.upper_bound,
            range_text=row.range_text,
            source_type=source_type,
        )
        stats["created_or_updated"] += 1

    return stats


@transaction.atomic
def reprocess_orphan_fields(
    *,
    queryset=None,
    normalized_names: Iterable[str] | None = None,
) -> dict[str, int]:
    """Retry pending orphan rows after alias or mapping updates."""

    orphans = queryset if queryset is not None else CheckupOrphanField.objects.all()
    orphans = orphans.filter(status=OrphanFieldStatus.PENDING)
    if normalized_names:
        orphans = orphans.filter(normalized_name__in=list(normalized_names))

    orphan_list = list(
        orphans.select_related("report_image", "checkup_item", "patient")
    )
    if not orphan_list:
        return {
            "resolved": 0,
            "missing_alias": 0,
            "missing_mapping": 0,
            "invalid_decimal": 0,
        }

    normalized_name_set = {item.normalized_name for item in orphan_list}
    aliases = {
        alias.normalized_name: alias
        for alias in StandardFieldAlias.objects.select_related("standard_field").filter(
            normalized_name__in=normalized_name_set,
            is_active=True,
            standard_field__is_active=True,
        )
    }
    mapping_pairs = set(
        CheckupFieldMapping.objects.filter(
            is_active=True,
            standard_field__is_active=True,
            checkup_item_id__in={item.checkup_item_id for item in orphan_list},
        ).values_list("checkup_item_id", "standard_field_id")
    )

    stats = {
        "resolved": 0,
        "missing_alias": 0,
        "missing_mapping": 0,
        "invalid_decimal": 0,
    }

    for orphan in orphan_list:
        alias = aliases.get(orphan.normalized_name)
        if alias is None:
            stats["missing_alias"] += 1
            continue

        pair = (orphan.checkup_item_id, alias.standard_field_id)
        if pair not in mapping_pairs:
            stats["missing_mapping"] += 1
            continue

        if (
            alias.standard_field.value_type == StandardFieldValueType.DECIMAL
            and orphan.raw_value
            and _coerce_decimal(orphan.raw_value) is None
        ):
            stats["invalid_decimal"] += 1
            continue

        result_value = _upsert_result_value(
            report_image=orphan.report_image,
            patient_id=orphan.patient_id,
            checkup_item_id=orphan.checkup_item_id,
            report_date=orphan.report_date,
            standard_field=alias.standard_field,
            raw_name=orphan.raw_name,
            raw_value=orphan.raw_value,
            item_code=orphan.item_code,
            unit=orphan.unit,
            lower_bound=orphan.lower_bound,
            upper_bound=orphan.upper_bound,
            range_text=orphan.range_text,
            source_type=CheckupResultSourceType.MIGRATED,
        )
        orphan.delete()
        stats["resolved"] += 1

    return stats
