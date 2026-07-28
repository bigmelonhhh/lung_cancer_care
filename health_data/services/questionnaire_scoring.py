"""问卷计分规则。"""

from collections.abc import Sequence
from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError


EQ5D5L_CODE = "Q_EQ5D5L"
EQVAS_CODE = "Q_EQVAS"


def is_eq5d5l_code(code: str | None) -> bool:
    """判断问卷编码是否精确匹配 EQ-5D-5L 专用计分规则。"""
    return bool(code and code.upper() == EQ5D5L_CODE)


def is_eqvas_code(code: str | None) -> bool:
    """判断问卷编码是否精确匹配 EQ-VAS 数字评分规则。"""
    return bool(code and code.upper() == EQVAS_CODE)


class Eq5d5lChinaCalculator:
    """根据五维等级计算中国大陆 EQ-5D-5L 健康效用指数。"""

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
        if len(levels) != len(cls.DIMENSION_DEDUCTIONS):
            raise ValidationError("EQ-5D-5L 必须包含五个健康维度。")

        total_deduction = Decimal("0")
        for index, level in enumerate(levels):
            if isinstance(level, bool) or not isinstance(level, int) or level not in range(1, 6):
                raise ValidationError("EQ-5D-5L 健康维度等级必须为 1 至 5 的整数。")
            total_deduction += cls.DIMENSION_DEDUCTIONS[index][level]

        utility = Decimal("1") - total_deduction
        return utility.quantize(cls.RESULT_QUANTUM, rounding=ROUND_HALF_UP)
