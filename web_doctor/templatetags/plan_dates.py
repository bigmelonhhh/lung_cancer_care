from datetime import timedelta

from django import template

register = template.Library()


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


@register.filter(name="plan_table_min_width_px")
def plan_table_min_width_px(value):
    try:
        cycle_days = int(value)
    except (TypeError, ValueError):
        cycle_days = 21
    if cycle_days <= 0:
        cycle_days = 21
    return 384 + (cycle_days * 32)
