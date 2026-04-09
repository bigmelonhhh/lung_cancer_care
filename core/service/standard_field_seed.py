"""Idempotent seed sync for structured checkup master data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from core.utils.normalization import normalize_standard_field_name


DEFAULT_STANDARD_FIELD_SEED_PATH = (
    Path(__file__).resolve().parent.parent / "seed_data" / "standard_fields_v1_20260402.json"
)


def load_standard_field_seed(path: str | Path | None = None) -> dict[str, Any]:
    seed_path = Path(path) if path else DEFAULT_STANDARD_FIELD_SEED_PATH
    return json.loads(seed_path.read_text(encoding="utf-8"))


def sync_standard_field_seed(
    *,
    standard_field_model,
    alias_model,
    mapping_model,
    checkup_model,
    seed_data: Mapping[str, Any] | None = None,
    path: str | Path | None = None,
) -> dict[str, int]:
    """
    Sync built-in standard field seed data.

    Rules:
    - idempotent, safe to run repeatedly
    - create missing rows only
    - do not overwrite existing rows
    - skip mappings when the target checkup item is absent
    """

    data = dict(seed_data or load_standard_field_seed(path))
    stats = {
        "created_fields": 0,
        "skipped_fields": 0,
        "created_aliases": 0,
        "skipped_aliases": 0,
        "created_mappings": 0,
        "skipped_mappings": 0,
        "missing_checkups": 0,
    }

    field_cache: dict[str, Any] = {}

    for item in data.get("standard_fields", []):
        local_code = str(item["local_code"]).strip()
        field, created = standard_field_model.objects.get_or_create(
            local_code=local_code,
            defaults={
                "english_abbr": (item.get("english_abbr") or "").strip(),
                "chinese_name": (item.get("chinese_name") or "").strip(),
                "value_type": item.get("value_type") or "DECIMAL",
                "default_unit": (item.get("default_unit") or "").strip(),
                "description": (item.get("description") or "").strip(),
                "is_active": bool(item.get("is_active", True)),
                "sort_order": int(item.get("sort_order") or 0),
            },
        )
        field_cache[local_code] = field
        stats["created_fields" if created else "skipped_fields"] += 1

    for item in data.get("aliases", []):
        field_code = str(item["field_code"]).strip()
        standard_field = field_cache.get(field_code)
        if standard_field is None:
            standard_field = standard_field_model.objects.get(local_code=field_code)
            field_cache[field_code] = standard_field

        alias_name = str(item["alias_name"]).strip()
        normalized_name = (
            str(item.get("normalized_name")).strip()
            if item.get("normalized_name")
            else normalize_standard_field_name(alias_name)
        )
        _, created = alias_model.objects.get_or_create(
            normalized_name=normalized_name,
            defaults={
                "standard_field": standard_field,
                "alias_name": alias_name,
                "is_active": bool(item.get("is_active", True)),
                "notes": (item.get("notes") or "").strip(),
            },
        )
        stats["created_aliases" if created else "skipped_aliases"] += 1

    for item in data.get("mappings", []):
        field_code = str(item["field_code"]).strip()
        standard_field = field_cache.get(field_code)
        if standard_field is None:
            standard_field = standard_field_model.objects.get(local_code=field_code)
            field_cache[field_code] = standard_field

        checkup = None
        checkup_code = (item.get("checkup_code") or "").strip()
        checkup_name = (item.get("checkup_name") or "").strip()
        if checkup_code:
            checkup = checkup_model.objects.filter(code=checkup_code).first()
        if checkup is None and checkup_name:
            checkup = checkup_model.objects.filter(name=checkup_name).first()

        if checkup is None:
            stats["missing_checkups"] += 1
            continue

        _, created = mapping_model.objects.get_or_create(
            checkup_item=checkup,
            standard_field=standard_field,
            defaults={
                "sort_order": int(item.get("sort_order") or 0),
                "is_active": bool(item.get("is_active", True)),
            },
        )
        stats["created_mappings" if created else "skipped_mappings"] += 1

    return stats
