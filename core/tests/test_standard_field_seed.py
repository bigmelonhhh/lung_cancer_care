from pathlib import Path

from django.db import IntegrityError, transaction
from django.test import TestCase

from core.models import CheckupFieldMapping, CheckupLibrary, StandardField, StandardFieldAlias, StandardFieldValueType
from core.service.standard_field_seed import (
    DEFAULT_STANDARD_FIELD_SEED_PATH,
    load_standard_field_seed,
    sync_standard_field_seed,
)


class StandardFieldModelTests(TestCase):
    def test_local_code_is_unique(self):
        StandardField.objects.create(local_code="WBC_MODEL_UNIQ", chinese_name="白细胞计数测试")

        with self.assertRaises(IntegrityError):
            StandardField.objects.create(local_code="WBC_MODEL_UNIQ", chinese_name="重复字段")

    def test_normalized_name_is_global_unique(self):
        field = StandardField.objects.create(local_code="WBC_ALIAS_UNIQ", chinese_name="白细胞计数别名测试")
        StandardFieldAlias.objects.create(standard_field=field, alias_name="白细胞计数测试别名")

        with self.assertRaises(IntegrityError), transaction.atomic():
            StandardFieldAlias.objects.create(standard_field=field, alias_name="  白细胞计数测试别名 ")

    def test_checkup_mapping_is_unique(self):
        checkup = CheckupLibrary.objects.create(name="血常规", code="BLOOD_ROUTINE")
        field = StandardField.objects.create(local_code="WBC_MAPPING_UNIQ", chinese_name="白细胞计数映射测试")
        CheckupFieldMapping.objects.create(checkup_item=checkup, standard_field=field)

        with self.assertRaises(IntegrityError), transaction.atomic():
            CheckupFieldMapping.objects.create(checkup_item=checkup, standard_field=field)


class StandardFieldSeedSyncTests(TestCase):
    def test_sync_creates_missing_records_and_is_idempotent(self):
        checkup = CheckupLibrary.objects.create(name="血常规", code="XCG")
        seed_data = {
            "standard_fields": [
                {
                    "local_code": "WBC_SYNC_TEST",
                    "english_abbr": "WBC-T",
                    "chinese_name": "白细胞计数同步测试",
                    "value_type": StandardFieldValueType.DECIMAL,
                    "default_unit": "10^9/L",
                }
            ],
            "aliases": [
                {"field_code": "WBC_SYNC_TEST", "alias_name": "WBC同步测试"},
                {"field_code": "WBC_SYNC_TEST", "alias_name": "白细胞计数同步测试"},
            ],
            "mappings": [
                {
                    "checkup_code": "BLOOD_ROUTINE",
                    "checkup_name": "血常规",
                    "field_code": "WBC_SYNC_TEST",
                }
            ],
        }

        first_stats = sync_standard_field_seed(
            standard_field_model=StandardField,
            alias_model=StandardFieldAlias,
            mapping_model=CheckupFieldMapping,
            checkup_model=CheckupLibrary,
            seed_data=seed_data,
        )
        self.assertEqual(first_stats["created_fields"], 1)
        self.assertEqual(first_stats["created_aliases"], 2)
        self.assertEqual(first_stats["created_mappings"], 1)

        field = StandardField.objects.get(local_code="WBC_SYNC_TEST")
        field.chinese_name = "运营自定义名称"
        field.save(update_fields=["chinese_name"])

        second_stats = sync_standard_field_seed(
            standard_field_model=StandardField,
            alias_model=StandardFieldAlias,
            mapping_model=CheckupFieldMapping,
            checkup_model=CheckupLibrary,
            seed_data=seed_data,
        )
        self.assertEqual(second_stats["skipped_fields"], 1)
        self.assertEqual(second_stats["skipped_aliases"], 2)
        self.assertEqual(second_stats["skipped_mappings"], 1)
        self.assertEqual(
            StandardField.objects.get(local_code="WBC_SYNC_TEST").chinese_name,
            "运营自定义名称",
        )
        self.assertTrue(CheckupFieldMapping.objects.filter(checkup_item=checkup, standard_field=field).exists())

    def test_builtin_seed_file_is_present_and_parseable(self):
        self.assertTrue(Path(DEFAULT_STANDARD_FIELD_SEED_PATH).exists())

        stats = sync_standard_field_seed(
            standard_field_model=StandardField,
            alias_model=StandardFieldAlias,
            mapping_model=CheckupFieldMapping,
            checkup_model=CheckupLibrary,
            path=DEFAULT_STANDARD_FIELD_SEED_PATH,
        )
        self.assertGreater(StandardField.objects.count(), 10)
        self.assertGreater(StandardFieldAlias.objects.count(), 10)
        self.assertGreater(stats["created_fields"] + stats["skipped_fields"], 10)
        self.assertGreater(stats["created_aliases"] + stats["skipped_aliases"], 10)

        second_stats = sync_standard_field_seed(
            standard_field_model=StandardField,
            alias_model=StandardFieldAlias,
            mapping_model=CheckupFieldMapping,
            checkup_model=CheckupLibrary,
            path=DEFAULT_STANDARD_FIELD_SEED_PATH,
        )

        self.assertEqual(second_stats["created_fields"], 0)
        self.assertEqual(second_stats["created_aliases"], 0)
        self.assertGreater(second_stats["skipped_fields"], 10)
        self.assertGreater(second_stats["skipped_aliases"], 10)

    def test_builtin_seed_contains_myocardial_marker_bundle(self):
        seed_data = load_standard_field_seed(DEFAULT_STANDARD_FIELD_SEED_PATH)

        field_codes = {item["local_code"] for item in seed_data["standard_fields"]}
        self.assertTrue({"CTNI", "CTNT", "MYO", "CK_MB", "H_FABP", "NT_PROBNP"}.issubset(field_codes))

        alias_pairs = {(item["field_code"], item["alias_name"]) for item in seed_data["aliases"]}
        self.assertIn(("NT_PROBNP", "N端脑钠肽前体"), alias_pairs)
        self.assertIn(("MYO", "肌红蛋白"), alias_pairs)
        self.assertIn(("H_FABP", "心型脂肪酸结合蛋白"), alias_pairs)

        myocardial_mapping_codes = {
            item["field_code"]
            for item in seed_data["mappings"]
            if item["checkup_code"] == "MYOCARDIAL_MARKER"
        }
        self.assertEqual(
            myocardial_mapping_codes,
            {"CTNI", "CTNT", "MYO", "CK_MB", "H_FABP", "NT_PROBNP"},
        )
