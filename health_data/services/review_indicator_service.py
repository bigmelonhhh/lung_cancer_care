"""复查指标（核心关注指标）共享服务。

承载医生端与患者端共用的复查指标能力：
- 标准指标库目录（CheckupLibrary + CheckupFieldMapping）构建
- 患者核心关注指标配置（indicator_preferences.followup_review）读取
- 结构化复查结果（CheckupResultValue）的序列查询、列表与图表聚合

配置写入（save_followup_review_preferences）仍保留在医生端视图层，
患者端仅只读消费医生配置，详见 docs/adr/0001-patient-review-metrics-readonly.md。
"""

from __future__ import annotations

import calendar
import logging
from datetime import date, timedelta

from django.db.models import Prefetch

from core.models import (
    CheckupFieldMapping,
    CheckupLibrary,
    StandardFieldValueType,
)
from health_data.models import CheckupResultValue
from users.models import PatientProfile

logger = logging.getLogger(__name__)

FOLLOWUP_REVIEW_PREFERENCES_KEY = "followup_review"
INDICATOR_PREFERENCES_VERSION = 1

# 与一般监测列表的 WEEKDAY_MAP 口径保持一致（星期一到星期日）
_WEEKDAY_LABELS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def build_followup_review_catalog() -> tuple[list[dict], dict[int, dict], list[int]]:
    """构建复查指标标准库目录。

    返回 (review_catalog, mapping_meta, all_mapping_ids)：
    - review_catalog：按检查项分组的字段列表，供配置弹窗渲染
    - mapping_meta：mapping_id -> 字段与检查项元信息
    - all_mapping_ids：全部有效 mapping_id
    """
    review_mapping_qs = (
        CheckupFieldMapping.objects.filter(
            is_active=True,
            standard_field__is_active=True,
        )
        .select_related("standard_field")
        .order_by("sort_order", "id")
    )
    checkup_items = list(
        CheckupLibrary.objects.filter(is_active=True)
        .prefetch_related(
            Prefetch(
                "standard_field_mappings",
                queryset=review_mapping_qs,
                to_attr="active_standard_field_mappings",
            )
        )
        .order_by("sort_order", "name", "id")
    )

    review_catalog = []
    mapping_meta: dict[int, dict] = {}
    all_mapping_ids = []
    for checkup in checkup_items:
        fields = []
        for mapping in getattr(checkup, "active_standard_field_mappings", []):
            standard_field = mapping.standard_field
            selectable = standard_field.value_type == StandardFieldValueType.DECIMAL
            field_name = standard_field.chinese_name or standard_field.english_abbr or standard_field.local_code or ""
            field_abbr = standard_field.english_abbr or ""
            field_display_name = f"{field_name}({field_abbr})" if field_abbr else field_name
            field_item = {
                "mapping_id": mapping.id,
                "field_id": standard_field.id,
                "field_code": standard_field.local_code or "",
                "field_name": field_name,
                "field_display_name": field_display_name,
                "abbr": field_abbr,
                "unit": standard_field.default_unit or "",
                "value_type": standard_field.value_type,
                "selectable": selectable,
            }
            fields.append(field_item)
            mapping_meta[mapping.id] = {
                **field_item,
                "checkup_id": checkup.id,
                "checkup_code": checkup.code or "",
                "checkup_name": checkup.name or "",
                "category_name": checkup.get_category_display(),
            }
            all_mapping_ids.append(mapping.id)
        review_catalog.append(
            {
                "checkup_id": checkup.id,
                "checkup_code": checkup.code or "",
                "checkup_name": checkup.name or "",
                "category_name": checkup.get_category_display(),
                "fields": fields,
            }
        )

    return review_catalog, mapping_meta, all_mapping_ids


def normalize_followup_review_mapping_ids(
    raw_mapping_ids: list[str] | list[int] | None,
    mapping_meta: dict[int, dict] | None = None,
) -> list[int]:
    """清洗核心关注指标 mapping_id 列表：剔除无效、不可选与重复项。"""
    if mapping_meta is None:
        _, mapping_meta, _ = build_followup_review_catalog()

    normalized_mapping_ids = []
    seen_mapping_ids = set()
    for mapping_id_raw in raw_mapping_ids or []:
        try:
            mapping_id = int(mapping_id_raw)
        except (TypeError, ValueError):
            continue
        mapping_info = mapping_meta.get(mapping_id)
        if (
            not mapping_info
            or not mapping_info["selectable"]
            or mapping_id in seen_mapping_ids
        ):
            continue
        normalized_mapping_ids.append(mapping_id)
        seen_mapping_ids.add(mapping_id)
    return normalized_mapping_ids


def get_saved_followup_review_mapping_ids(patient: PatientProfile) -> list[int]:
    """读取患者档案中保存的核心关注指标 mapping_id（医生配置，原始值未清洗）。"""
    preferences = getattr(patient, "indicator_preferences", {}) or {}
    if not isinstance(preferences, dict):
        return []
    followup_review_preferences = preferences.get(FOLLOWUP_REVIEW_PREFERENCES_KEY, {})
    if not isinstance(followup_review_preferences, dict):
        return []
    selected_mapping_ids = followup_review_preferences.get("selected_mapping_ids", [])
    if not isinstance(selected_mapping_ids, list):
        return []
    return selected_mapping_ids


def get_patient_selected_mapping_meta(patient: PatientProfile) -> tuple[list[int], dict[int, dict]]:
    """返回患者已配置且有效的核心关注指标 mapping_id 及元信息。"""
    _, mapping_meta, _ = build_followup_review_catalog()
    raw_selected = get_saved_followup_review_mapping_ids(patient)
    selected_mapping_ids = normalize_followup_review_mapping_ids(
        raw_selected, mapping_meta=mapping_meta
    )
    return selected_mapping_ids, mapping_meta


def query_followup_review_series(
    *,
    patient: PatientProfile,
    mapping_ids: list[int],
    mapping_meta: dict[int, dict],
    date_list: list[date],
    start_date: date,
    end_date: date,
) -> tuple[dict[int, list[float | None]], dict[int, list[float]], dict[int, str]]:
    """按日期序列聚合各指标的数值趋势（同日多条取最后一条）。"""
    if not mapping_ids:
        return {}, {}, {}

    selected_pairs = {
        (mapping_meta[mapping_id]["checkup_id"], mapping_meta[mapping_id]["field_id"])
        for mapping_id in mapping_ids
    }
    checkup_ids = {checkup_id for checkup_id, _ in selected_pairs}
    field_ids = {field_id for _, field_id in selected_pairs}

    result_values = (
        CheckupResultValue.objects.filter(
            patient=patient,
            checkup_item_id__in=checkup_ids,
            standard_field_id__in=field_ids,
            report_date__range=(start_date, end_date),
            value_numeric__isnull=False,
        )
        .order_by("report_date", "id")
        .only(
            "id",
            "checkup_item_id",
            "standard_field_id",
            "report_date",
            "value_numeric",
            "unit",
        )
    )

    values_by_pair_and_date: dict[tuple[int, int], dict[date, float]] = {
        pair: {} for pair in selected_pairs
    }
    unit_by_pair: dict[tuple[int, int], str] = {}
    for result_value in result_values:
        pair = (result_value.checkup_item_id, result_value.standard_field_id)
        if pair not in selected_pairs:
            continue
        values_by_pair_and_date[pair][result_value.report_date] = float(result_value.value_numeric)
        if result_value.unit:
            unit_by_pair[pair] = result_value.unit

    series_by_mapping: dict[int, list[float | None]] = {}
    values_by_mapping: dict[int, list[float]] = {}
    unit_by_mapping: dict[int, str] = {}
    for mapping_id in mapping_ids:
        mapping_info = mapping_meta[mapping_id]
        pair = (mapping_info["checkup_id"], mapping_info["field_id"])
        day_value_map = values_by_pair_and_date.get(pair, {})
        series_data = [day_value_map.get(day) for day in date_list]
        series_by_mapping[mapping_id] = series_data
        values_by_mapping[mapping_id] = [
            value for value in series_data if value is not None
        ]
        unit_by_mapping[mapping_id] = unit_by_pair.get(pair) or mapping_info["unit"]

    return series_by_mapping, values_by_mapping, unit_by_mapping


def _format_number(value: float | None) -> str:
    """数值展示格式化：整数不带小数点，小数去尾零。"""
    if value is None:
        return ""
    if float(value).is_integer():
        return str(int(value))
    return f"{float(value):g}"


def build_patient_review_metric_stats(
    patient: PatientProfile,
    start_date: date,
    end_date: date,
) -> list[dict]:
    """构建患者端复查指标列表统计（医生配置的全部有效指标，含 0 记录项）。

    每一项包含 mapping_id、显示名、检查分类名、记录次数与最新值信息，
    统计范围限定在 [start_date, end_date]。
    """
    selected_mapping_ids, mapping_meta = get_patient_selected_mapping_meta(patient)
    if not selected_mapping_ids:
        return []

    selected_pairs = {
        (mapping_meta[mapping_id]["checkup_id"], mapping_meta[mapping_id]["field_id"])
        for mapping_id in selected_mapping_ids
    }
    checkup_ids = {checkup_id for checkup_id, _ in selected_pairs}
    field_ids = {field_id for _, field_id in selected_pairs}

    result_values = (
        CheckupResultValue.objects.filter(
            patient=patient,
            checkup_item_id__in=checkup_ids,
            standard_field_id__in=field_ids,
            report_date__range=(start_date, end_date),
            value_numeric__isnull=False,
        )
        .order_by("report_date", "id")
        .only(
            "id",
            "checkup_item_id",
            "standard_field_id",
            "report_date",
            "value_numeric",
            "unit",
            "abnormal_flag",
        )
    )

    count_by_pair: dict[tuple[int, int], int] = {}
    latest_by_pair: dict[tuple[int, int], CheckupResultValue] = {}
    for result_value in result_values:
        pair = (result_value.checkup_item_id, result_value.standard_field_id)
        if pair not in selected_pairs:
            continue
        count_by_pair[pair] = count_by_pair.get(pair, 0) + 1
        latest_by_pair[pair] = result_value

    stats: list[dict] = []
    for mapping_id in selected_mapping_ids:
        mapping_info = mapping_meta[mapping_id]
        pair = (mapping_info["checkup_id"], mapping_info["field_id"])
        latest = latest_by_pair.get(pair)
        latest_value = float(latest.value_numeric) if latest else None
        stats.append(
            {
                "mapping_id": mapping_id,
                "field_name": mapping_info["field_name"],
                "abbr": mapping_info["abbr"],
                "title": mapping_info["field_display_name"],
                "category_name": mapping_info["checkup_name"],
                "count": count_by_pair.get(pair, 0),
                "latest_value": _format_number(latest_value),
                "latest_unit": (latest.unit if latest and latest.unit else mapping_info["unit"]),
                "abnormal_flag": latest.abnormal_flag if latest else "",
            }
        )
    return stats


def get_review_metric_mapping_info(mapping_id: int | str) -> dict | None:
    """按 mapping_id 查询单个有效且可选的指标元信息，无效返回 None。"""
    try:
        mapping_id_int = int(mapping_id)
    except (TypeError, ValueError):
        return None
    _, mapping_meta, _ = build_followup_review_catalog()
    mapping_info = mapping_meta.get(mapping_id_int)
    if not mapping_info or not mapping_info["selectable"]:
        return None
    return mapping_info


def record_to_detail_item(result_value: CheckupResultValue, mapping_info: dict) -> dict:
    """将单条 CheckupResultValue 转换为详情页展示结构。"""
    report_date = result_value.report_date
    unit = result_value.unit or mapping_info["unit"]

    if result_value.range_text:
        reference_range = result_value.range_text
    elif result_value.lower_bound is not None and result_value.upper_bound is not None:
        reference_range = (
            f"{_format_number(float(result_value.lower_bound))} ~ "
            f"{_format_number(float(result_value.upper_bound))}"
        )
    else:
        reference_range = ""
    if reference_range and unit:
        reference_range = f"{reference_range} {unit}"

    return {
        "id": result_value.id,
        "date_str": report_date.strftime("%Y-%m-%d"),
        "weekday": _WEEKDAY_LABELS[report_date.weekday()],
        "field_display_name": mapping_info["field_display_name"],
        "value": _format_number(float(result_value.value_numeric)),
        "unit": unit,
        "reference_range": reference_range,
        "abnormal_flag": result_value.abnormal_flag,
        "source_label": "患者上传",
    }


def build_review_metric_chart(
    patient: PatientProfile,
    mapping_id: int,
    month: str,
) -> dict | None:
    """构建单指标指定月份（YYYY-MM）的按日折线数据（同日多条取最后一条）。"""
    mapping_info = get_review_metric_mapping_info(mapping_id)
    if not mapping_info:
        return None

    try:
        year, month_num = (int(part) for part in month.split("-"))
        days_in_month = calendar.monthrange(year, month_num)[1]
    except (ValueError, AttributeError):
        return None
    start_date = date(year, month_num, 1)
    end_date = date(year, month_num, days_in_month)

    date_list = [start_date + timedelta(days=i) for i in range(days_in_month)]
    series_by_mapping, values_by_mapping, unit_by_mapping = query_followup_review_series(
        patient=patient,
        mapping_ids=[mapping_id],
        mapping_meta={mapping_id: mapping_info},
        date_list=date_list,
        start_date=start_date,
        end_date=end_date,
    )
    values = values_by_mapping.get(mapping_id, [])
    return {
        "title": mapping_info["field_display_name"],
        "unit": unit_by_mapping.get(mapping_id) or mapping_info["unit"],
        "date_labels": [day.strftime("%m-%d") for day in date_list],
        "data": series_by_mapping.get(mapping_id, [None] * days_in_month),
        "has_data": bool(values),
    }
