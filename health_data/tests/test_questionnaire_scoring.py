from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from health_data.services import questionnaire_scoring
from health_data.services.questionnaire_scoring import (
    Eq5d5lChinaCalculator,
    EqVasCalculator,
)


class Eq5d5lChinaCalculatorTests(SimpleTestCase):
    def test_special_questionnaire_codes_use_case_insensitive_exact_match(self):
        self.assertTrue(hasattr(questionnaire_scoring, "is_eq5d5l_code"))
        self.assertTrue(questionnaire_scoring.is_eq5d5l_code("Q_EQ5D5L"))
        self.assertTrue(questionnaire_scoring.is_eq5d5l_code("q_eq5d5l"))
        self.assertFalse(questionnaire_scoring.is_eq5d5l_code("Q_EQ5D5L_CUSTOM"))
        self.assertTrue(questionnaire_scoring.is_eqvas_code("Q_EQVAS"))
        self.assertTrue(questionnaire_scoring.is_eqvas_code("q_eqvas"))
        self.assertFalse(questionnaire_scoring.is_eqvas_code("Q_EQVAS_CUSTOM"))

    def test_calculates_china_value_set_examples(self):
        self.assertEqual(
            Eq5d5lChinaCalculator.calculate((1, 1, 1, 1, 1)),
            Decimal("1.00"),
        )
        self.assertEqual(
            Eq5d5lChinaCalculator.calculate((2, 1, 3, 2, 4)),
            Decimal("0.55"),
        )
        self.assertEqual(
            Eq5d5lChinaCalculator.calculate((5, 5, 5, 5, 5)),
            Decimal("-0.39"),
        )

    def test_rejects_wrong_dimension_count_and_invalid_levels(self):
        invalid_levels = (
            (1, 1, 1, 1),
            (1, 1, 1, 1, 1, 1),
            (0, 1, 1, 1, 1),
            (6, 1, 1, 1, 1),
            ("1", 1, 1, 1, 1),
        )
        for levels in invalid_levels:
            with self.subTest(levels=levels), self.assertRaises(ValidationError):
                Eq5d5lChinaCalculator.calculate(levels)

    def test_grades_eq5d5l_by_most_severe_dimension(self):
        cases = (
            ((1, 1, 1, 1, 1), 1),
            ((2, 1, 1, 1, 1), 2),
            ((2, 3, 1, 1, 1), 3),
            ((1, 1, 4, 1, 1), 4),
            ((1, 1, 1, 1, 5), 4),
        )

        for levels, expected_grade in cases:
            with self.subTest(levels=levels):
                self.assertEqual(
                    Eq5d5lChinaCalculator.grade(levels),
                    expected_grade,
                )


class EqVasCalculatorTests(SimpleTestCase):
    def test_calculates_and_grades_absolute_score_boundaries(self):
        cases = (
            ("100", 1),
            ("80", 1),
            ("79", 2),
            ("60", 2),
            ("59", 3),
            ("40", 3),
            ("39", 4),
            ("0", 4),
        )

        for value_text, expected_grade in cases:
            with self.subTest(value_text=value_text):
                self.assertEqual(
                    EqVasCalculator.calculate(value_text),
                    Decimal(value_text),
                )
                self.assertEqual(
                    EqVasCalculator.grade(value_text),
                    expected_grade,
                )

    def test_optional_blank_has_zero_score_but_no_grade(self):
        self.assertEqual(EqVasCalculator.calculate(None), Decimal("0.00"))
        self.assertIsNone(EqVasCalculator.grade(None))

    def test_rejects_invalid_eqvas_values(self):
        for value_text in ("-1", "101", "1.5", "1e2", "+1", " 1", "1 ", "一"):
            with self.subTest(value_text=value_text), self.assertRaises(
                ValidationError
            ):
                EqVasCalculator.calculate(value_text)
