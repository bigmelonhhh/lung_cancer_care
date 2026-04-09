from datetime import date
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase

from core.models import (
    CheckupFieldMapping,
    CheckupLibrary,
    StandardField,
    StandardFieldAlias,
    StandardFieldValueType,
)
from health_data.models import (
    CheckupOrphanField,
    CheckupResultAbnormalFlag,
    CheckupResultSourceType,
    CheckupResultValue,
    OrphanFieldStatus,
    ReportImage,
    ReportUpload,
)
from health_data.services.checkup_results import (
    ingest_structured_checkup_rows,
    reprocess_orphan_fields,
)
from users.models import PatientProfile


class CheckupResultServiceTests(TestCase):
    def setUp(self):
        self.numeric_raw_name = "白细胞计数测试项"
        self.numeric_normalized_name = self.numeric_raw_name
        self.text_raw_name = "影像描述测试项"
        self.text_normalized_name = self.text_raw_name
        self.patient = PatientProfile.objects.create(phone="13900001000", name="结构化患者")
        self.blood_routine = CheckupLibrary.objects.create(name="血常规", code="BLOOD_ROUTINE")
        self.chest_ct = CheckupLibrary.objects.create(name="胸部CT", code="CT_CHEST")
        self.upload = ReportUpload.objects.create(patient=self.patient)
        self.blood_image = ReportImage.objects.create(
            upload=self.upload,
            image_url="https://example.com/blood.png",
            record_type=ReportImage.RecordType.CHECKUP,
            checkup_item=self.blood_routine,
            report_date=date(2026, 4, 1),
        )
        self.ct_image = ReportImage.objects.create(
            upload=self.upload,
            image_url="https://example.com/chest-ct.png",
            record_type=ReportImage.RecordType.CHECKUP,
            checkup_item=self.chest_ct,
            report_date=date(2026, 4, 2),
        )
        self.wbc_field = StandardField.objects.create(
            local_code="WBC_SERVICE_TEST",
            english_abbr="WBC-T",
            chinese_name="白细胞计数服务测试",
            value_type=StandardFieldValueType.DECIMAL,
            default_unit="10^9/L",
        )
        self.findings_field = StandardField.objects.create(
            local_code="IMG_FINDINGS_SERVICE_TEST",
            chinese_name="影像描述服务测试",
            value_type=StandardFieldValueType.TEXT,
        )

    def test_ingest_creates_orphan_when_alias_is_missing(self):
        stats = ingest_structured_checkup_rows(
            report_image=self.blood_image,
            rows=[
                {
                    "name": self.numeric_raw_name,
                    "value": "5.6",
                    "unit": "10^9/L",
                    "lower_bound": "3.5",
                    "upper_bound": "9.5",
                }
            ],
        )

        self.assertEqual(stats, {"created_or_updated": 0, "orphans": 1})
        orphan = CheckupOrphanField.objects.get(
            report_image=self.blood_image,
            normalized_name=self.numeric_normalized_name,
        )
        self.assertEqual(orphan.status, OrphanFieldStatus.PENDING)
        self.assertEqual(orphan.value_numeric, Decimal("5.6"))
        self.assertIn("未命中标准字段别名", orphan.notes)
        self.assertEqual(CheckupResultValue.objects.count(), 0)

    def test_ingest_creates_orphan_when_mapping_is_missing(self):
        StandardFieldAlias.objects.create(
            standard_field=self.wbc_field,
            alias_name=self.numeric_raw_name,
        )

        stats = ingest_structured_checkup_rows(
            report_image=self.blood_image,
            rows=[{"name": self.numeric_raw_name, "value": "5.6"}],
        )

        self.assertEqual(stats, {"created_or_updated": 0, "orphans": 1})
        orphan = CheckupOrphanField.objects.get(
            report_image=self.blood_image,
            normalized_name=self.numeric_normalized_name,
        )
        self.assertIn("未配置该标准字段映射", orphan.notes)
        self.assertEqual(CheckupResultValue.objects.count(), 0)

    def test_ingest_upserts_numeric_result_when_alias_and_mapping_exist(self):
        StandardFieldAlias.objects.create(
            standard_field=self.wbc_field,
            alias_name=self.numeric_raw_name,
        )
        CheckupFieldMapping.objects.create(
            checkup_item=self.blood_routine,
            standard_field=self.wbc_field,
            sort_order=100,
        )

        first_stats = ingest_structured_checkup_rows(
            report_image=self.blood_image,
            rows=[
                {
                    "name": self.numeric_raw_name,
                    "value": "5.6",
                    "unit": "10^9/L",
                    "lower_bound": "3.5",
                    "upper_bound": "9.5",
                    "range_text": "3.5-9.5",
                }
            ],
        )
        self.assertEqual(first_stats, {"created_or_updated": 1, "orphans": 0})

        result = CheckupResultValue.objects.get(report_image=self.blood_image, standard_field=self.wbc_field)
        self.assertEqual(result.patient, self.patient)
        self.assertEqual(result.value_numeric, Decimal("5.6"))
        self.assertEqual(result.abnormal_flag, CheckupResultAbnormalFlag.NORMAL)
        self.assertEqual(result.source_type, CheckupResultSourceType.AI)
        self.assertEqual(result.range_text, "3.5-9.5")

        second_stats = ingest_structured_checkup_rows(
            report_image=self.blood_image,
            rows=[
                {
                    "name": self.numeric_raw_name,
                    "value": "10.1",
                    "unit": "10^9/L",
                    "lower_bound": "3.5",
                    "upper_bound": "9.5",
                }
            ],
        )
        self.assertEqual(second_stats, {"created_or_updated": 1, "orphans": 0})
        self.assertEqual(CheckupResultValue.objects.count(), 1)

        result.refresh_from_db()
        self.assertEqual(result.value_numeric, Decimal("10.1"))
        self.assertEqual(result.abnormal_flag, CheckupResultAbnormalFlag.HIGH)

    def test_ingest_writes_text_result_for_text_field(self):
        StandardFieldAlias.objects.create(
            standard_field=self.findings_field,
            alias_name=self.text_raw_name,
        )
        CheckupFieldMapping.objects.create(
            checkup_item=self.chest_ct,
            standard_field=self.findings_field,
            sort_order=10,
        )

        stats = ingest_structured_checkup_rows(
            report_image=self.ct_image,
            rows=[{"name": self.text_raw_name, "value": "右肺上叶结节较前缩小。"}],
        )

        self.assertEqual(stats, {"created_or_updated": 1, "orphans": 0})
        result = CheckupResultValue.objects.get(report_image=self.ct_image, standard_field=self.findings_field)
        self.assertEqual(result.value_text, "右肺上叶结节较前缩小。")
        self.assertIsNone(result.value_numeric)
        self.assertEqual(result.abnormal_flag, CheckupResultAbnormalFlag.UNKNOWN)

    def test_reprocess_orphan_fields_resolves_pending_rows_idempotently(self):
        ingest_structured_checkup_rows(
            report_image=self.blood_image,
            rows=[{"name": self.numeric_raw_name, "value": "5.6", "unit": "10^9/L"}],
        )
        orphan = CheckupOrphanField.objects.get(
            report_image=self.blood_image,
            normalized_name=self.numeric_normalized_name,
        )
        self.assertEqual(orphan.status, OrphanFieldStatus.PENDING)

        StandardFieldAlias.objects.create(
            standard_field=self.wbc_field,
            alias_name=self.numeric_raw_name,
        )
        CheckupFieldMapping.objects.create(
            checkup_item=self.blood_routine,
            standard_field=self.wbc_field,
            sort_order=100,
        )

        first_stats = reprocess_orphan_fields(normalized_names=[self.numeric_normalized_name])
        self.assertEqual(first_stats, {"resolved": 1, "missing_alias": 0, "missing_mapping": 0})

        orphan.refresh_from_db()
        result = CheckupResultValue.objects.get(report_image=self.blood_image, standard_field=self.wbc_field)
        self.assertEqual(orphan.status, OrphanFieldStatus.RESOLVED)
        self.assertEqual(orphan.resolved_standard_field, self.wbc_field)
        self.assertEqual(orphan.resolved_result_value, result)
        self.assertEqual(result.source_type, CheckupResultSourceType.MIGRATED)

        second_stats = reprocess_orphan_fields(normalized_names=[self.numeric_normalized_name])
        self.assertEqual(second_stats, {"resolved": 0, "missing_alias": 0, "missing_mapping": 0})
        self.assertEqual(CheckupResultValue.objects.count(), 1)

    def test_ingest_creates_orphan_when_decimal_value_cannot_be_parsed(self):
        StandardFieldAlias.objects.create(
            standard_field=self.wbc_field,
            alias_name=self.numeric_raw_name,
        )
        CheckupFieldMapping.objects.create(
            checkup_item=self.blood_routine,
            standard_field=self.wbc_field,
            sort_order=100,
        )

        stats = ingest_structured_checkup_rows(
            report_image=self.blood_image,
            rows=[{"name": self.numeric_raw_name, "value": "未出结果"}],
        )

        self.assertEqual(stats, {"created_or_updated": 0, "orphans": 1})
        orphan = CheckupOrphanField.objects.get(
            report_image=self.blood_image,
            normalized_name=self.numeric_normalized_name,
        )
        self.assertIn("数值解析失败", orphan.notes)
        self.assertEqual(CheckupResultValue.objects.count(), 0)

    def test_result_value_is_unique_per_report_image_and_standard_field(self):
        CheckupResultValue.objects.create(
            patient=self.patient,
            report_image=self.blood_image,
            checkup_item=self.blood_routine,
            standard_field=self.wbc_field,
            report_date=self.blood_image.report_date,
            raw_name=self.numeric_raw_name,
            normalized_name=self.numeric_normalized_name,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            CheckupResultValue.objects.create(
                patient=self.patient,
                report_image=self.blood_image,
                checkup_item=self.blood_routine,
                standard_field=self.wbc_field,
                report_date=self.blood_image.report_date,
                raw_name=f"{self.numeric_raw_name}重复",
                normalized_name=f"{self.numeric_normalized_name}重复",
            )

    def test_orphan_field_is_unique_per_report_image_and_normalized_name(self):
        CheckupOrphanField.objects.create(
            patient=self.patient,
            report_image=self.blood_image,
            checkup_item=self.blood_routine,
            report_date=self.blood_image.report_date,
            raw_name=self.numeric_raw_name,
            normalized_name=self.numeric_normalized_name,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            CheckupOrphanField.objects.create(
                patient=self.patient,
                report_image=self.blood_image,
                checkup_item=self.blood_routine,
                report_date=self.blood_image.report_date,
                raw_name=f"{self.numeric_raw_name}重复",
                normalized_name=self.numeric_normalized_name,
            )
