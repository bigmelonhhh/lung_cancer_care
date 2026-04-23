import json
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from core.models import CheckupFieldMapping, CheckupLibrary, StandardField, StandardFieldAlias, StandardFieldValueType
from health_data.models import CheckupOrphanField, CheckupResultSourceType, CheckupResultValue, ReportImage, ReportUpload
from users.models import CustomUser, PatientProfile


class ReportImageAdminIntegrationTests(TestCase):
    def setUp(self):
        self.admin_user = CustomUser.objects.create_superuser(
            username="review_admin",
            password="strong-pass-123",
            phone="13900005000",
        )
        self.client.force_login(self.admin_user)
        self.patient = PatientProfile.objects.create(phone="13900005001", name="后台患者")
        self.checkup = CheckupLibrary.objects.create(name="血常规", code="BLOOD_ROUTINE_ADMIN", is_active=True)
        self.upload = ReportUpload.objects.create(patient=self.patient)
        self.report_image = ReportImage.objects.create(
            upload=self.upload,
            image_url="https://example.com/admin-review-image.png",
            record_type=ReportImage.RecordType.CHECKUP,
            checkup_item=self.checkup,
            report_date=date(2026, 4, 18),
            ai_parse_status="SUCCESS",
            ai_structured_json={
                "is_medical_report": True,
                "report_category": "血常规",
                "report_time_raw": "2026-04-18 08:00",
                "items": [{"item_name": "AI白细胞", "item_value": "5.6"}],
            },
        )
        self.standard_field = StandardField.objects.create(
            local_code="WBC_ADMIN_REVIEW",
            english_abbr="WBC-ADMIN-REVIEW",
            chinese_name="白细胞后台修订测试",
            value_type=StandardFieldValueType.DECIMAL,
            default_unit="10^9/L",
        )
        StandardFieldAlias.objects.create(
            standard_field=self.standard_field,
            alias_name="人工白细胞",
        )
        StandardFieldAlias.objects.create(
            standard_field=self.standard_field,
            alias_name="AI白细胞",
        )
        CheckupFieldMapping.objects.create(
            checkup_item=self.checkup,
            standard_field=self.standard_field,
            sort_order=100,
        )

    def test_change_page_renders_review_editor_and_preview(self):
        response = self.client.get(
            reverse("admin:health_data_reportimage_change", args=[self.report_image.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "report-review-layout")
        self.assertContains(response, "report-image-viewer")
        self.assertContains(response, "report-image-viewer-fit")
        self.assertContains(response, "report-image-viewer-actual")
        self.assertContains(response, "report-image-viewer-zoom-in")
        self.assertContains(response, "report-image-viewer-zoom-out")
        self.assertContains(response, "report-image-viewer-reset")
        self.assertContains(response, "report-image-viewer-state")
        self.assertContains(response, "review-items-editor")
        self.assertContains(response, self.report_image.image_url)
        self.assertContains(response, "name=\"report_category\"")
        self.assertContains(response, "height: calc(100vh - 32px)")
        self.assertContains(response, "max-height: calc(100vh - 32px)")
        self.assertContains(response, "overflow-y: auto")
        self.assertContains(response, "适应窗口")
        self.assertContains(response, "100%")
        self.assertContains(response, "原始 AI JSON（排查用）")
        self.assertContains(response, "已关联标准字段")
        self.assertContains(response, "标准字段：")
        self.assertContains(response, "addEventListener(\"wheel\"")
        self.assertContains(response, "addEventListener(\"dblclick\"")
        self.assertContains(response, "report-image-viewer--chrome-hidden")
        self.assertContains(response, ".report-image-viewer__empty[hidden]")
        self.assertContains(response, "rightColumn.appendChild(imageFieldset)")
        self.assertContains(response, "rightColumn.appendChild(aiFieldset)")
        self.assertNotContains(response, "leftColumn.appendChild(imageFieldset)")
        self.assertNotContains(response, "leftColumn.appendChild(aiFieldset)")
        self.assertNotContains(response, 'target="_blank"')

    def test_change_page_highlights_orphan_rows_with_reason(self):
        self.report_image.reviewed_structured_json = {
            "is_medical_report": True,
            "report_category": "血常规",
            "report_time_raw": "2026-04-18 08:00",
            "items": [{"item_name": "缺失别名项目", "item_value": "7.1"}],
        }
        self.report_image.save(update_fields=["reviewed_structured_json"])

        response = self.client.get(
            reverse("admin:health_data_reportimage_change", args=[self.report_image.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "report-item-row--orphan")
        self.assertContains(response, "孤儿字段")
        self.assertContains(response, "未命中标准字段别名")
        self.assertContains(response, "补别名库或修正项目名。")

    def test_change_page_save_persists_reviewed_payload_and_rebuilds_results(self):
        response = self.client.post(
            reverse("admin:health_data_reportimage_change", args=[self.report_image.pk]),
            data={
                "is_medical_report": "on",
                "report_category": "血常规",
                "hospital_name": "协和医院",
                "patient_name": "张三",
                "patient_gender": "男",
                "patient_age": "56岁",
                "sample_type": "血液",
                "report_name": "血常规报告",
                "report_time_raw": "2026-04-18 09:00",
                "exam_time_raw": "2026-04-18 08:30",
                "exam_findings": "检查所见",
                "doctor_interpretation": "医生解读",
                "reviewed_items_json": json.dumps(
                    [
                        {
                            "item_name": "人工白细胞",
                            "item_value": "8.2",
                            "abnormal_flag": "high",
                            "reference_low": "3.5",
                            "reference_high": "9.5",
                            "unit": "10^9/L",
                            "item_code": "MANUAL-001",
                        }
                    ],
                    ensure_ascii=False,
                ),
                "_save": "保存",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.report_image.refresh_from_db()
        self.assertEqual(self.report_image.reviewed_by, self.admin_user)
        self.assertEqual(self.report_image.reviewed_structured_json["hospital_name"], "协和医院")
        result = CheckupResultValue.objects.get(
            report_image=self.report_image,
            standard_field=self.standard_field,
        )
        self.assertEqual(result.value_numeric, Decimal("8.2"))
        self.assertEqual(result.source_type, CheckupResultSourceType.MANUAL)
        self.assertContains(response, "已保存人工修订，已重建 1 条正式结果，0 条孤儿字段。")

    def test_change_page_clear_reviewed_payload_rebuilds_from_ai(self):
        self.report_image.reviewed_structured_json = {
            "is_medical_report": True,
            "report_category": "血常规",
            "report_time_raw": "2026-04-18 09:00",
            "items": [{"item_name": "人工白细胞", "item_value": "8.2"}],
        }
        self.report_image.reviewed_by = self.admin_user
        self.report_image.reviewed_at = self.report_image.upload.created_at
        self.report_image.save(update_fields=["reviewed_structured_json", "reviewed_by", "reviewed_at"])
        CheckupResultValue.objects.create(
            patient=self.patient,
            report_image=self.report_image,
            checkup_item=self.checkup,
            standard_field=self.standard_field,
            report_date=self.report_image.report_date,
            raw_name="人工白细胞",
            normalized_name="人工白细胞",
            raw_value="8.2",
            value_numeric=Decimal("8.2"),
            source_type=CheckupResultSourceType.MANUAL,
        )

        response = self.client.post(
            reverse("admin:health_data_reportimage_change", args=[self.report_image.pk]),
            data={"_clear_reviewed_json": "1"},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.report_image.refresh_from_db()
        self.assertIsNone(self.report_image.reviewed_structured_json)
        self.assertIsNone(self.report_image.reviewed_by)
        result = CheckupResultValue.objects.get(
            report_image=self.report_image,
            standard_field=self.standard_field,
        )
        self.assertEqual(result.value_numeric, Decimal("5.6"))
        self.assertEqual(result.source_type, CheckupResultSourceType.AI)
        self.assertContains(response, "已清空人工修订，已重建 1 条正式结果，0 条孤儿字段。")

    def test_orphan_changelist_shows_preview_and_report_link(self):
        orphan = CheckupOrphanField.objects.create(
            patient=self.patient,
            report_image=self.report_image,
            checkup_item=self.checkup,
            report_date=self.report_image.report_date,
            raw_name="未知项目",
            normalized_name="未知项目",
            raw_value="1.0",
        )

        response = self.client.get(reverse("admin:health_data_checkuporphanfield_changelist"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.report_image.image_url)
        self.assertContains(
            response,
            reverse("admin:health_data_reportimage_change", args=[self.report_image.pk]),
        )
        self.assertContains(response, f"报告图片 #{orphan.report_image_id}")

    @patch("health_data.tasks.reprocess_orphan_fields_task.delay")
    def test_orphan_retry_matching_enqueues_async_task_for_selected_rows(self, delay_mock):
        resolvable_orphan = CheckupOrphanField.objects.create(
            patient=self.patient,
            report_image=self.report_image,
            checkup_item=self.checkup,
            report_date=self.report_image.report_date,
            raw_name="AI白细胞",
            normalized_name="AI白细胞",
            raw_value="6.1",
        )
        unresolved_orphan = CheckupOrphanField.objects.create(
            patient=self.patient,
            report_image=self.report_image,
            checkup_item=self.checkup,
            report_date=self.report_image.report_date,
            raw_name="未知项目",
            normalized_name="未知项目",
            raw_value="1.0",
        )

        response = self.client.post(
            reverse("admin:health_data_checkuporphanfield_changelist"),
            data={
                "action": "retry_matching",
                "_selected_action": [str(resolvable_orphan.pk)],
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        delay_mock.assert_called_once_with(orphan_ids=[resolvable_orphan.pk])
        self.assertTrue(CheckupOrphanField.objects.filter(pk=resolvable_orphan.pk).exists())
        self.assertTrue(CheckupOrphanField.objects.filter(pk=unresolved_orphan.pk).exists())
        self.assertFalse(
            CheckupResultValue.objects.filter(
                report_image=self.report_image,
                standard_field=self.standard_field,
            ).exists()
        )
        self.assertContains(
            response,
            "已提交 1 条孤儿字段的异步重跑任务。",
        )
        self.assertContains(response, "AI白细胞")
        self.assertContains(response, "未知项目")
