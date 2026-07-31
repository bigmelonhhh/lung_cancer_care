"""问卷计分规则。"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from django.core.exceptions import ValidationError


EQ5D5L_CODE = "Q_EQ5D5L"
EQVAS_CODE = "Q_EQVAS"


@dataclass(frozen=True)
class QuestionnaireGradeResult:
    """问卷分级结果及可审计的规则上下文。"""

    grade_level: int | None
    rule_version: str
    score_label: str
    details: dict[str, Any] = field(default_factory=dict)


def is_eq5d5l_code(code: str | None) -> bool:
    """判断问卷编码是否精确匹配 EQ-5D-5L 专用计分规则。"""
    return bool(code and code.upper() == EQ5D5L_CODE)


def is_eqvas_code(code: str | None) -> bool:
    """判断问卷编码是否精确匹配 EQ-VAS 数字评分规则。"""
    return bool(code and code.upper() == EQVAS_CODE)


class Eq5d5lChinaCalculator:
    """根据五维等级计算中国大陆 EQ-5D-5L 健康效用指数。"""

    DIMENSION_NAMES = (
        "行动能力",
        "自我照顾",
        "日常活动",
        "疼痛/不适",
        "焦虑/抑郁",
    )
    DIMENSION_DEDUCTIONS = (
        {
            1: Decimal("0"),
            2: Decimal("0.066"),
            3: Decimal("0.158"),
            4: Decimal("0.287"),
            5: Decimal("0.345"),
        },
        {
            1: Decimal("0"),
            2: Decimal("0.048"),
            3: Decimal("0.116"),
            4: Decimal("0.210"),
            5: Decimal("0.253"),
        },
        {
            1: Decimal("0"),
            2: Decimal("0.045"),
            3: Decimal("0.107"),
            4: Decimal("0.194"),
            5: Decimal("0.233"),
        },
        {
            1: Decimal("0"),
            2: Decimal("0.058"),
            3: Decimal("0.138"),
            4: Decimal("0.252"),
            5: Decimal("0.302"),
        },
        {
            1: Decimal("0"),
            2: Decimal("0.049"),
            3: Decimal("0.118"),
            4: Decimal("0.215"),
            5: Decimal("0.258"),
        },
    )
    RESULT_QUANTUM = Decimal("0.01")

    @classmethod
    def calculate(cls, levels: Sequence[int]) -> Decimal:
        """计算五维健康效用指数，并在最终结果执行两位小数四舍五入。"""
        validated_levels = cls._validate_levels(levels)

        total_deduction = Decimal("0")
        for index, level in enumerate(validated_levels):
            total_deduction += cls.DIMENSION_DEDUCTIONS[index][level]

        utility = Decimal("1") - total_deduction
        return utility.quantize(cls.RESULT_QUANTUM, rounding=ROUND_HALF_UP)

    @classmethod
    def grade(cls, levels: Sequence[int]) -> int:
        """按五个维度中的最严重困难水平返回项目分级。"""
        max_level = max(cls._validate_levels(levels))
        return 4 if max_level >= 4 else max_level

    @classmethod
    def _validate_levels(cls, levels: Sequence[int]) -> tuple[int, ...]:
        if len(levels) != len(cls.DIMENSION_DEDUCTIONS):
            raise ValidationError("EQ-5D-5L 必须包含五个健康维度。")

        validated_levels = tuple(levels)
        for level in validated_levels:
            if (
                isinstance(level, bool)
                or not isinstance(level, int)
                or level not in range(1, 6)
            ):
                raise ValidationError(
                    "EQ-5D-5L 健康维度等级必须为 1 至 5 的整数。"
                )
        return validated_levels


class EqVasCalculator:
    """校验并计算 EQ-VAS 评分及项目分级。"""

    VALUE_PATTERN = re.compile(r"(?:0|[1-9]|[1-9][0-9]|100)", re.ASCII)

    @classmethod
    def calculate(cls, value_text: str | None) -> Decimal:
        """返回0至100整数评分；非必填空值按既定口径返回0。"""
        value = cls._parse(value_text)
        return Decimal("0.00") if value is None else Decimal(value)

    @classmethod
    def grade(cls, value_text: str | None) -> int | None:
        """按80/60/40项目阈值返回分级，空值不参与分级。"""
        value = cls._parse(value_text)
        if value is None:
            return None
        if value >= 80:
            return 1
        if value >= 60:
            return 2
        if value >= 40:
            return 3
        return 4

    @classmethod
    def _parse(cls, value_text: str | None) -> int | None:
        if value_text is None:
            return None
        if (
            not isinstance(value_text, str)
            or cls.VALUE_PATTERN.fullmatch(value_text) is None
        ):
            raise ValidationError("EQ-VAS 自评分必须为 0 至 100 的整数。")
        return int(value_text)
