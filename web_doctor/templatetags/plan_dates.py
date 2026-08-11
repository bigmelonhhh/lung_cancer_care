from datetime import timedelta

from django import template

register = template.Library()

PLAN_TABLE_FIXED_WIDTH_PX = 384
PLAN_DAY_MIN_WIDTH_PX = 32
PLAN_DAY_MAX_WIDTH_PX = 40


@register.filter(name="add_days")
def add_days(value, days):
    if value is None or days is None:
        return value
    try:
        return value + timedelta(days=int(days))
    except (TypeError, ValueError):
        return value


@register.filter(name="day_offsets")
def day_offsets(value):
    try:
        cycle_days = int(value)
    except (TypeError, ValueError):
        return []
    if cycle_days <= 0:
        return []
    return list(range(cycle_days))


@register.filter(name="week_ranges")
def week_ranges(value):
    try:
        cycle_days = int(value)
    except (TypeError, ValueError):
        return []
    if cycle_days <= 0:
        return []

    ranges = []
    for start_day in range(1, cycle_days + 1, 7):
        end_day = min(start_day + 6, cycle_days)
        ranges.append(
            {
                "start_day": start_day,
                "end_day": end_day,
                "start_offset": start_day - 1,
                "end_offset": end_day - 1,
                "span": end_day - start_day + 1,
            }
        )
    return ranges


@register.filter(name="plan_table_min_width_px")
def plan_table_min_width_px(value):
    cycle_days = _normalize_cycle_days(value)
    return PLAN_TABLE_FIXED_WIDTH_PX + (cycle_days * PLAN_DAY_MIN_WIDTH_PX)


@register.filter(name="plan_table_max_width_px")
def plan_table_max_width_px(value):
    cycle_days = _normalize_cycle_days(value)
    return PLAN_TABLE_FIXED_WIDTH_PX + (cycle_days * PLAN_DAY_MAX_WIDTH_PX)


def _normalize_cycle_days(value):
    try:
        cycle_days = int(value)
    except (TypeError, ValueError):
        cycle_days = 21
    if cycle_days <= 0:
        cycle_days = 21
    return cycle_days
