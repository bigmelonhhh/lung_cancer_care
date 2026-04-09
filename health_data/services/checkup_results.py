"""Services for structured checkup result storage and orphan reprocessing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Iterable

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


@dataclass
class StructuredRowPayload:
    """Normalized row payload for ingestion."""

    raw_name: str
    raw_value: str
    unit: str = ""
    lower_bound: Decimal | None = None
    upper_bound: Decimal | None = None
    range_text: str = ""
    raw_line_text: str = ""


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

        result_value = _upsert_result_value(
            report_image=orphan.report_image,
            patient_id=orphan.patient_id,
            checkup_item_id=orphan.checkup_item_id,
            report_date=orphan.report_date,
            standard_field=alias.standard_field,
            raw_name=orphan.raw_name,
            raw_value=orphan.raw_value,
            unit=orphan.unit,
            lower_bound=orphan.lower_bound,
            upper_bound=orphan.upper_bound,
            range_text=orphan.range_text,
            source_type=CheckupResultSourceType.MIGRATED,
        )
        orphan.status = OrphanFieldStatus.RESOLVED
        orphan.resolved_standard_field = alias.standard_field
        orphan.resolved_result_value = result_value
        orphan.resolved_at = timezone.now()
        orphan.save(
            update_fields=[
                "status",
                "resolved_standard_field",
                "resolved_result_value",
                "resolved_at",
                "updated_at",
            ]
        )
        stats["resolved"] += 1

    return stats
