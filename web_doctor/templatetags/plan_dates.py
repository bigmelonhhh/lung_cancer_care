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
