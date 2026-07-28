from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from health_data.services import questionnaire_scoring
from health_data.services.questionnaire_scoring import Eq5d5lChinaCalculator


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
