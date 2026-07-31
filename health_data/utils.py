from __future__ import annotations

from decimal import Decimal
from typing import Optional


def _to_decimal(value: Optional[Decimal | float | int]) -> Optional[Decimal]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001
        return None


def _calc_deviation_level(
    current: Optional[Decimal | float | int],
    lower: Optional[Decimal | float | int],
    upper: Optional[Decimal | float | int],
) -> int:
    """
    通用“相对正常范围波动比例 -> 等级”计算。

    规则：
    - 在 [lower, upper] 范围内视为 0 级；
    - 偏离比例 < 10%：0 级；
    - 偏离比例 = 10%：1 级；
    - (10%, 20%]：2 级；
    - > 20%：3 级。
    """
    cur = _to_decimal(current)
    lo = _to_decimal(lower)
    hi = _to_decimal(upper)

    if cur is None or lo is None or hi is None or lo <= 0 or hi <= 0 or lo > hi:
        return 0

    # 在正常范围内
    if lo <= cur <= hi:
        return 0

    if cur < lo:
        ratio = (lo - cur) / lo
    else:  # cur > hi
        ratio = (cur - hi) / hi

    if ratio < Decimal("0.10"):
        return 0
    if ratio == Decimal("0.10"):
        return 1
    if ratio <= Decimal("0.20"):
        return 2
    return 3


def evaluate_spo2_level(
    current_spo2: Optional[Decimal | float | int],
    *,
    baseline_spo2: Optional[Decimal | float | int] = None,
    confirmed_drop: bool = False,
) -> int:
    """
    血氧异常等级评估。

    业务规则（数值部分）：
    - ≥95%：0 级（正常）；
    - 93–94%：1 级；
    - 90–92%：2 级；
    - ≤89%：3 级。

    基线下降部分：
    - 较个人基线下降 ≥3%：至少 1 级；
    - 较基线下降 ≥5%，且“持续/复测确认”时，可提升到 2 级。
    """
    cur = _to_decimal(current_spo2)
    if cur is None:
        return 0

    level_from_abs = 0
    if cur >= Decimal("95"):
        level_from_abs = 0
    elif cur >= Decimal("93"):
        level_from_abs = 1
    elif cur >= Decimal("90"):
        level_from_abs = 2
    else:
        level_from_abs = 3

    level_from_baseline = 0
    base = _to_decimal(baseline_spo2)
    if base and base > 0:
        drop = base - cur
        drop_pct = drop / base
        if drop_pct >= Decimal("0.05"):
            level_from_baseline = 2 if confirmed_drop else 1
        elif drop_pct >= Decimal("0.03"):
            level_from_baseline = 1

    return max(level_from_abs, level_from_baseline)


def evaluate_blood_pressure_level(
    sbp: Optional[Decimal | float | int],
    dbp: Optional[Decimal | float | int],
    *,
    sbp_lower: Decimal | float | int = 120,
    sbp_upper: Decimal | float | int = 140,
    dbp_lower: Decimal | float | int = 80,
    dbp_upper: Decimal | float | int = 90,
) -> int:
    """
    血压异常等级评估。

    规则：
    - 正常范围：收缩压 120–140，舒张压 80–90（可通过参数覆盖）。
    - 高于上限或低于下限的“波动值比例”：
      - <10%：0 级；
      - =10%：1 级；
      - (10%, 20%]：2 级；
      - >20%：3 级。
    - 最终等级取收缩压、舒张压两者中较高的那个。
    """
    level_sbp = _calc_deviation_level(sbp, sbp_lower, sbp_upper)
    level_dbp = _calc_deviation_level(dbp, dbp_lower, dbp_upper)
    return max(level_sbp, level_dbp)


def evaluate_heart_rate_level(
    heart_rate: Optional[Decimal | float | int],
    *,
    hr_lower: Decimal | float | int = 51,
    hr_upper: Decimal | float | int = 90,
) -> int:
    """
    心率异常等级评估。

    规则：
    - 正常范围：51–90（可通过参数覆盖）。
    - 高于上限或低于下限的“波动值比例”：
      - <10%：0 级；
      - =10%：1 级；
      - (10%, 20%]：2 级；
      - >20%：3 级。
    """
    return _calc_deviation_level(heart_rate, hr_lower, hr_upper)


def evaluate_temperature_level(
    current_temp: Optional[Decimal | float | int],
    *,
    has_48h_persistent_high: bool = False,
    has_72h_persistent_high: bool = False,
) -> int:
    """
    体温异常等级评估。

    规则：
    - 单次值判断：
      - < 38.0°C：0 级（正常）；
      - > 38.0°C 且 < 38.5°C：1 级；
      - 38.5–39.4°C：2 级；
      - ≥39.5°C 或 ≤35.0°C：3 级。
    - 时间维度判断：
      - 连续 48 小时高于 38°C：至少 2 级；
      - 连续 72 小时高于 38°C：3 级。
    - 最终结果取“单次值等级”和“时间维度等级”中较高者。
    """
    temp = _to_decimal(current_temp)

    level_from_time = 0
    if has_72h_persistent_high:
        level_from_time = 3
    elif has_48h_persistent_high:
        level_from_time = 2

    if temp is None:
        return level_from_time

    level_from_value = 0
    if temp <= Decimal("35.0") or temp >= Decimal("39.5"):
        level_from_value = 3
    elif temp >= Decimal("38.5"):
        level_from_value = 2
    elif temp > Decimal("38.0"):
        level_from_value = 1
    else:
        level_from_value = 0

    return max(level_from_value, level_from_time)


def evaluate_glucose_level(
    value: Optional[Decimal | float | int],
    measurement_context: str | None,
) -> int:
    """按测量场景评估血糖异常等级。"""
    current = _to_decimal(value)
    if current is None:
        return 0
    if current < Decimal("3.0"):
        return 2
    if current < Decimal("3.9"):
        return 1
    if measurement_context == "fasting":
        return 1 if current >= Decimal("7.0") else 0
    return 1 if current >= Decimal("11.1") else 0


def evaluate_blood_ketone_level(
    value: Optional[Decimal | float | int],
) -> int:
    """评估血酮异常等级。"""
    current = _to_decimal(value)
    if current is None or current < Decimal("0.6"):
        return 0
    if current <= Decimal("1.5"):
        return 1
    if current <= Decimal("3.0"):
        return 2
    return 3


def evaluate_uric_acid_level(
    value: Optional[Decimal | float | int],
) -> int:
    """评估尿酸异常等级。"""
    current = _to_decimal(value)
    if current is None:
        return 0
    return 1 if current > Decimal("420") else 0
