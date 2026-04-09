from django.test import SimpleTestCase

from core.utils.normalization import normalize_standard_field_name


class StandardFieldNormalizationTests(SimpleTestCase):
    def test_parenthetical_abbreviation_is_dropped(self):
        self.assertEqual(
            normalize_standard_field_name("白细胞计数(WBC)"),
            "白细胞计数",
        )

    def test_parenthetical_chinese_name_is_dropped(self):
        self.assertEqual(
            normalize_standard_field_name("WBC（白细胞计数）"),
            "WBC",
        )

    def test_short_code_suffix_in_brackets_is_preserved(self):
        self.assertEqual(
            normalize_standard_field_name("LP(a)"),
            "LPA",
        )
