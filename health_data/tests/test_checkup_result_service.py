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
    analyze_report_image_structured_items,
    build_report_image_metrics_payload,
    ingest_structured_checkup_rows,
    ignore_ai_sync_warnings,
    rebuild_report_image_structured_results,
    reprocess_orphan_fields,
    sync_lab_results_from_ai_json,
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
                    "item_code": "WBC-001",
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
        self.assertEqual(orphan.item_code, "WBC-001")
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
                    "item_code": "WBC-001",
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
        self.assertEqual(result.item_code, "WBC-001")
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

    def test_sync_lab_results_from_ai_json_writes_result_and_item_code(self):
        StandardFieldAlias.objects.create(
            standard_field=self.wbc_field,
            alias_name=self.numeric_raw_name,
        )
        CheckupFieldMapping.objects.create(
            checkup_item=self.blood_routine,
            standard_field=self.wbc_field,
            sort_order=100,
        )
        self.blood_image.ai_parse_status = "SUCCESS"
        self.blood_image.ai_structured_json = {
            "is_medical_report": True,
            "report_category": "血常规",
            "report_time_raw": "2026-04-01 08:00",
            "items": [
                {
                    "item_name": self.numeric_raw_name,
                    "item_value": "5.6",
                    "reference_low": "3.5",
                    "reference_high": "9.5",
                    "unit": "10^9/L",
                    "item_code": "WBC-001",
                }
            ],
        }
        self.blood_image.save(update_fields=["ai_parse_status", "ai_structured_json"])

        stats = sync_lab_results_from_ai_json(self.blood_image)

        self.assertEqual(stats["status"], "synced")
        result = CheckupResultValue.objects.get(report_image=self.blood_image, standard_field=self.wbc_field)
        self.assertEqual(result.item_code, "WBC-001")

    def test_sync_lab_results_from_ai_json_blocks_category_conflict(self):
        self.blood_image.ai_parse_status = "SUCCESS"
        self.blood_image.ai_structured_json = {
            "is_medical_report": True,
            "report_category": "血生化",
            "report_time_raw": "2026-04-01 08:00",
            "items": [{"item_name": self.numeric_raw_name, "item_value": "5.6"}],
        }
        self.blood_image.save(update_fields=["ai_parse_status", "ai_structured_json"])

        stats = sync_lab_results_from_ai_json(self.blood_image)

        self.assertEqual(stats["status"], "warning_blocked")
        self.blood_image.refresh_from_db()
        self.assertEqual(
            self.blood_image.ai_sync_warnings["report_category_conflict"]["status"],
            "pending",
        )
        self.assertEqual(CheckupResultValue.objects.count(), 0)

    def test_sync_lab_results_from_ai_json_blocks_report_date_conflict(self):
        self.blood_image.ai_parse_status = "SUCCESS"
        self.blood_image.ai_structured_json = {
            "is_medical_report": True,
            "report_category": "血常规",
            "report_time_raw": "2026-04-02 08:00",
            "items": [{"item_name": self.numeric_raw_name, "item_value": "5.6"}],
        }
        self.blood_image.save(update_fields=["ai_parse_status", "ai_structured_json"])

        stats = sync_lab_results_from_ai_json(self.blood_image)

        self.assertEqual(stats["status"], "warning_blocked")
        self.blood_image.refresh_from_db()
        self.assertEqual(
            self.blood_image.ai_sync_warnings["report_date_conflict"]["status"],
            "pending",
        )

    def test_sync_lab_results_from_ai_json_allows_ignored_warning(self):
        StandardFieldAlias.objects.create(
            standard_field=self.wbc_field,
            alias_name=self.numeric_raw_name,
        )
        CheckupFieldMapping.objects.create(
            checkup_item=self.blood_routine,
            standard_field=self.wbc_field,
            sort_order=100,
        )
        self.blood_image.ai_parse_status = "SUCCESS"
        self.blood_image.ai_structured_json = {
            "is_medical_report": True,
            "report_category": "血生化",
            "report_time_raw": "2026-04-01 08:00",
            "items": [
                {
                    "item_name": self.numeric_raw_name,
                    "item_value": "5.6",
                    "reference_low": "3.5",
                    "reference_high": "9.5",
                    "unit": "10^9/L",
                    "item_code": "WBC-001",
                }
            ],
        }
        self.blood_image.save(update_fields=["ai_parse_status", "ai_structured_json"])

        first_stats = sync_lab_results_from_ai_json(self.blood_image)
        self.assertEqual(first_stats["status"], "warning_blocked")

        ignore_ai_sync_warnings(self.blood_image, warning_keys=["report_category_conflict"])
        second_stats = sync_lab_results_from_ai_json(self.blood_image)

        self.assertEqual(second_stats["status"], "synced")
        result = CheckupResultValue.objects.get(report_image=self.blood_image, standard_field=self.wbc_field)
        self.assertEqual(result.item_code, "WBC-001")

    def test_sync_lab_results_from_ai_json_marks_warning_resolved_after_fix(self):
        self.blood_image.ai_parse_status = "SUCCESS"
        self.blood_image.ai_structured_json = {
            "is_medical_report": True,
            "report_category": "血生化",
            "report_time_raw": "2026-04-01 08:00",
            "items": [{"item_name": self.numeric_raw_name, "item_value": "5.6"}],
        }
        self.blood_image.save(update_fields=["ai_parse_status", "ai_structured_json"])

        first_stats = sync_lab_results_from_ai_json(self.blood_image)
        self.assertEqual(first_stats["status"], "warning_blocked")

        self.blood_image.checkup_item = CheckupLibrary.objects.create(name="血生化", code="BIOCHEM_FIX")
        self.blood_image.save(update_fields=["checkup_item"])
        second_stats = sync_lab_results_from_ai_json(self.blood_image)

        self.assertEqual(second_stats["status"], "synced")
        self.blood_image.refresh_from_db()
        self.assertEqual(
            self.blood_image.ai_sync_warnings["report_category_conflict"]["status"],
            "resolved",
        )

    def test_rebuild_prefers_reviewed_payload_and_marks_result_manual(self):
        StandardFieldAlias.objects.create(
            standard_field=self.wbc_field,
            alias_name="人工白细胞",
        )
        CheckupFieldMapping.objects.create(
            checkup_item=self.blood_routine,
            standard_field=self.wbc_field,
            sort_order=100,
        )
        self.blood_image.ai_parse_status = "SUCCESS"
        self.blood_image.ai_structured_json = {
            "is_medical_report": True,
            "report_category": "血常规",
            "report_time_raw": "2026-04-01 08:00",
            "items": [{"item_name": self.numeric_raw_name, "item_value": "5.6"}],
        }
        self.blood_image.reviewed_structured_json = {
            "is_medical_report": True,
            "report_category": "血常规",
            "report_time_raw": "2026-04-01 08:00",
            "items": [{"item_name": "人工白细胞", "item_value": "8.2", "item_code": "MANUAL-001"}],
        }
        self.blood_image.save(update_fields=["ai_parse_status", "ai_structured_json", "reviewed_structured_json"])

        stats = rebuild_report_image_structured_results(self.blood_image)

        self.assertEqual(stats["status"], "synced")
        result = CheckupResultValue.objects.get(report_image=self.blood_image, standard_field=self.wbc_field)
        self.assertEqual(result.value_numeric, Decimal("8.2"))
        self.assertEqual(result.item_code, "MANUAL-001")
        self.assertEqual(result.source_type, CheckupResultSourceType.MANUAL)

    def test_rebuild_clears_stale_rows_when_effective_items_become_empty(self):
        StandardFieldAlias.objects.create(
            standard_field=self.wbc_field,
            alias_name=self.numeric_raw_name,
        )
        CheckupFieldMapping.objects.create(
            checkup_item=self.blood_routine,
            standard_field=self.wbc_field,
            sort_order=100,
        )
        self.blood_image.ai_parse_status = "SUCCESS"
        self.blood_image.ai_structured_json = {
            "is_medical_report": True,
            "report_category": "血常规",
            "report_time_raw": "2026-04-01 08:00",
            "items": [{"item_name": self.numeric_raw_name, "item_value": "5.6"}],
        }
        self.blood_image.save(update_fields=["ai_parse_status", "ai_structured_json"])
        first_stats = rebuild_report_image_structured_results(self.blood_image)
        self.assertEqual(first_stats["status"], "synced")
        self.assertEqual(CheckupResultValue.objects.count(), 1)

        self.blood_image.reviewed_structured_json = {
            "is_medical_report": True,
            "report_category": "血常规",
            "report_time_raw": "2026-04-01 08:00",
            "items": [],
        }
        self.blood_image.save(update_fields=["reviewed_structured_json"])

        second_stats = rebuild_report_image_structured_results(self.blood_image)

        self.assertEqual(second_stats["status"], "synced")
        self.assertEqual(second_stats["created_or_updated"], 0)
        self.assertEqual(CheckupResultValue.objects.count(), 0)
        self.assertEqual(CheckupOrphanField.objects.count(), 0)

    def test_rebuild_non_medical_payload_clears_existing_rows(self):
        StandardFieldAlias.objects.create(
            standard_field=self.wbc_field,
            alias_name=self.numeric_raw_name,
        )
        CheckupFieldMapping.objects.create(
            checkup_item=self.blood_routine,
            standard_field=self.wbc_field,
            sort_order=100,
        )
        self.blood_image.ai_parse_status = "SUCCESS"
        self.blood_image.ai_structured_json = {
            "is_medical_report": True,
            "report_category": "血常规",
            "report_time_raw": "2026-04-01 08:00",
            "items": [{"item_name": self.numeric_raw_name, "item_value": "5.6"}],
        }
        self.blood_image.save(update_fields=["ai_parse_status", "ai_structured_json"])
        rebuild_report_image_structured_results(self.blood_image)
        self.assertEqual(CheckupResultValue.objects.count(), 1)

        self.blood_image.reviewed_structured_json = {
            "is_medical_report": False,
            "report_category": None,
            "report_time_raw": None,
            "items": [],
        }
        self.blood_image.save(update_fields=["reviewed_structured_json"])

        stats = rebuild_report_image_structured_results(self.blood_image)

        self.assertEqual(stats["status"], "synced")
        self.assertEqual(CheckupResultValue.objects.count(), 0)
        self.assertEqual(CheckupOrphanField.objects.count(), 0)

    def test_analyze_report_image_structured_items_marks_matched_and_orphan_rows(self):
        StandardFieldAlias.objects.create(
            standard_field=self.wbc_field,
            alias_name=self.numeric_raw_name,
        )
        CheckupFieldMapping.objects.create(
            checkup_item=self.blood_routine,
            standard_field=self.wbc_field,
            sort_order=100,
        )
        self.blood_image.reviewed_structured_json = {
            "is_medical_report": True,
            "report_category": "血常规",
            "report_time_raw": "2026-04-01 08:00",
            "items": [
                {"item_name": self.numeric_raw_name, "item_value": "5.6"},
                {"item_name": "未知项目", "item_value": "1.0"},
            ],
        }
        self.blood_image.save(update_fields=["reviewed_structured_json"])

        result = analyze_report_image_structured_items(self.blood_image)

        self.assertEqual(result[0]["status"], "matched")
        self.assertFalse(result[0]["is_orphan"])
        self.assertEqual(result[0]["standard_field_display"], self.wbc_field.chinese_name)
        self.assertEqual(result[1]["status"], "orphan")
        self.assertTrue(result[1]["is_orphan"])
        self.assertEqual(result[1]["reason"], "未命中标准字段别名")

    def test_analyze_report_image_structured_items_marks_decimal_parse_failure(self):
        StandardFieldAlias.objects.create(
            standard_field=self.wbc_field,
            alias_name=self.numeric_raw_name,
        )
        CheckupFieldMapping.objects.create(
            checkup_item=self.blood_routine,
            standard_field=self.wbc_field,
            sort_order=100,
        )
        self.blood_image.reviewed_structured_json = {
            "is_medical_report": True,
            "report_category": "血常规",
            "report_time_raw": "2026-04-01 08:00",
            "items": [{"item_name": self.numeric_raw_name, "item_value": "未出结果"}],
        }
        self.blood_image.save(update_fields=["reviewed_structured_json"])

        result = analyze_report_image_structured_items(self.blood_image)

        self.assertEqual(result[0]["status"], "orphan")
        self.assertEqual(result[0]["reason"], "数值解析失败")

    def test_build_report_image_metrics_payload_includes_previous_numeric_result(self):
        previous_image = ReportImage.objects.create(
            upload=self.upload,
            image_url="https://example.com/blood-prev.png",
            record_type=ReportImage.RecordType.CHECKUP,
            checkup_item=self.blood_routine,
            report_date=date(2026, 3, 30),
        )
        same_day_image = ReportImage.objects.create(
            upload=self.upload,
            image_url="https://example.com/blood-same-day.png",
            record_type=ReportImage.RecordType.CHECKUP,
            checkup_item=self.blood_routine,
            report_date=self.blood_image.report_date,
        )
        CheckupFieldMapping.objects.create(
            checkup_item=self.blood_routine,
            standard_field=self.wbc_field,
            sort_order=100,
        )
        CheckupResultValue.objects.create(
            patient=self.patient,
            report_image=previous_image,
            checkup_item=self.blood_routine,
            standard_field=self.wbc_field,
            report_date=previous_image.report_date,
            raw_name=self.numeric_raw_name,
            normalized_name=self.numeric_normalized_name,
            raw_value="4.2",
            value_numeric=Decimal("4.2"),
            unit="10^9/L",
            lower_bound=Decimal("3.5"),
            upper_bound=Decimal("9.5"),
            range_text="3.5-9.5",
        )
        CheckupResultValue.objects.create(
            patient=self.patient,
            report_image=same_day_image,
            checkup_item=self.blood_routine,
            standard_field=self.wbc_field,
            report_date=same_day_image.report_date,
            raw_name=self.numeric_raw_name,
            normalized_name=self.numeric_normalized_name,
            raw_value="4.9",
            value_numeric=Decimal("4.9"),
        )
        CheckupResultValue.objects.create(
            patient=self.patient,
            report_image=self.blood_image,
            checkup_item=self.blood_routine,
            standard_field=self.wbc_field,
            report_date=self.blood_image.report_date,
            raw_name=self.numeric_raw_name,
            normalized_name=self.numeric_normalized_name,
            raw_value="5.6",
            value_numeric=Decimal("5.6"),
            unit="10^9/L",
            lower_bound=Decimal("3.5"),
            upper_bound=Decimal("9.5"),
            range_text="3.5-9.5",
        )

        payload = build_report_image_metrics_payload(self.blood_image)

        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["title"], "复查-血常规")
        self.assertEqual(payload["report_date"], "2026-04-01")
        self.assertEqual(len(payload["rows"]), 1)
        row = payload["rows"][0]
        self.assertEqual(row["field_code"], "WBC_SERVICE_TEST")
        self.assertEqual(row["field_name"], "白细胞计数服务测试")
        self.assertEqual(row["current_value_display"], "5.6")
        self.assertEqual(row["unit"], "10^9/L")
        self.assertEqual(row["reference_range"], "3.5-9.5")
        self.assertEqual(row["previous_value_display"], "4.2")
        self.assertEqual(row["delta_display"], "+1.4")
        self.assertEqual(row["delta_direction"], "up")

    def test_build_report_image_metrics_payload_uses_text_fallback_for_text_field(self):
        previous_image = ReportImage.objects.create(
            upload=self.upload,
            image_url="https://example.com/ct-prev.png",
            record_type=ReportImage.RecordType.CHECKUP,
            checkup_item=self.chest_ct,
            report_date=date(2026, 3, 28),
        )
        CheckupResultValue.objects.create(
            patient=self.patient,
            report_image=previous_image,
            checkup_item=self.chest_ct,
            standard_field=self.findings_field,
            report_date=previous_image.report_date,
            raw_name=self.text_raw_name,
            normalized_name=self.text_normalized_name,
            raw_value="右肺结节稳定。",
            value_text="右肺结节稳定。",
        )
        CheckupResultValue.objects.create(
            patient=self.patient,
            report_image=self.ct_image,
            checkup_item=self.chest_ct,
            standard_field=self.findings_field,
            report_date=self.ct_image.report_date,
            raw_name=self.text_raw_name,
            normalized_name=self.text_normalized_name,
            raw_value="右肺上叶结节较前缩小。",
            value_text="右肺上叶结节较前缩小。",
        )

        payload = build_report_image_metrics_payload(self.ct_image)

        self.assertEqual(len(payload["rows"]), 1)
        row = payload["rows"][0]
        self.assertEqual(row["current_value_display"], "右肺上叶结节较前缩小。")
        self.assertEqual(row["previous_value_display"], "右肺结节稳定。")
        self.assertEqual(row["delta_display"], "-")
        self.assertEqual(row["delta_direction"], "none")

    def test_build_report_image_metrics_payload_returns_empty_message_when_no_results(self):
        payload = build_report_image_metrics_payload(self.blood_image)

        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["rows"], [])
        self.assertEqual(payload["empty_message"], "该图片暂无已匹配指标数据")

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
        self.assertEqual(first_stats, {"resolved": 1, "missing_alias": 0, "missing_mapping": 0, "invalid_decimal": 0})

        result = CheckupResultValue.objects.get(report_image=self.blood_image, standard_field=self.wbc_field)
        self.assertFalse(
            CheckupOrphanField.objects.filter(
                report_image=self.blood_image,
                normalized_name=self.numeric_normalized_name,
            ).exists()
        )
        self.assertEqual(result.source_type, CheckupResultSourceType.MIGRATED)

        second_stats = reprocess_orphan_fields(normalized_names=[self.numeric_normalized_name])
        self.assertEqual(second_stats, {"resolved": 0, "missing_alias": 0, "missing_mapping": 0, "invalid_decimal": 0})
        self.assertEqual(CheckupResultValue.objects.count(), 1)

    def test_reprocess_orphan_fields_keeps_decimal_parse_failures_pending(self):
        StandardFieldAlias.objects.create(
            standard_field=self.wbc_field,
            alias_name=self.numeric_raw_name,
        )
        CheckupFieldMapping.objects.create(
            checkup_item=self.blood_routine,
            standard_field=self.wbc_field,
            sort_order=100,
        )
        ingest_structured_checkup_rows(
            report_image=self.blood_image,
            rows=[{"name": self.numeric_raw_name, "value": "未出结果"}],
        )

        stats = reprocess_orphan_fields(normalized_names=[self.numeric_normalized_name])

        self.assertEqual(stats, {"resolved": 0, "missing_alias": 0, "missing_mapping": 0, "invalid_decimal": 1})
        orphan = CheckupOrphanField.objects.get(
            report_image=self.blood_image,
            normalized_name=self.numeric_normalized_name,
        )
        self.assertEqual(orphan.status, OrphanFieldStatus.PENDING)
        self.assertEqual(CheckupResultValue.objects.count(), 0)

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
