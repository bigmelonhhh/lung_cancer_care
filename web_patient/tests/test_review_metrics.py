"""患者端复查指标模块测试：健康档案 Tab 统计 + 复查指标详情页与数据接口。"""

from datetime import date, timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import (
    CheckupFieldMapping,
    CheckupLibrary,
    StandardField,
    StandardFieldValueType,
)
from health_data.models import CheckupResultAbnormalFlag, CheckupResultValue, ReportImage, UploadSource
from health_data.services.report_service import ReportUploadService
from market.models import Order, Product
from users.models import CustomUser, PatientProfile


class ReviewMetricTestBase(TestCase):
    """构造患者、标准字段映射与结构化复查结果的公共基类。"""

    def setUp(self):
        self.client = Client()
        self.user = CustomUser.objects.create_user(
            username="testpatient_review_metrics",
            password="password",
            wx_openid="test_openid_review_metrics",
        )
        self.patient = PatientProfile.objects.create(
            user=self.user, name="Test Patient", phone="13900002001"
        )
        self.client.force_login(self.user)

        self.checkup_item = CheckupLibrary.objects.create(
            name="血常规", code="REVIEW_METRIC_BLOOD_ROUTINE"
        )
        self.field_wbc = StandardField.objects.create(
            local_code="REVIEW_METRIC_WBC",
            english_abbr="WBC",
            chinese_name="白细胞计数",
            value_type=StandardFieldValueType.DECIMAL,
            default_unit="10^9/L",
        )
        self.mapping_wbc = CheckupFieldMapping.objects.create(
            checkup_item=self.checkup_item,
            standard_field=self.field_wbc,
        )

    def _create_paid_order(self, *, paid_at, duration_days):
        product = Product.objects.create(
            name="复查指标测试服务包", price=Decimal("199.00"), duration_days=duration_days
        )
        return Order.objects.create(
            patient=self.patient,
            product=product,
            amount=Decimal("199.00"),
            status=Order.Status.PAID,
            paid_at=paid_at,
        )

    def _create_result_value(self, report_date, value, *, abnormal_flag, image_suffix, **extra):
        ReportUploadService.create_upload(
            self.patient,
            images=[
                {
                    "image_url": f"https://example.com/review-metric-{image_suffix}.png",
                    "record_type": ReportImage.RecordType.CHECKUP,
                    "checkup_item_id": self.checkup_item.id,
                    "report_date": report_date,
                }
            ],
            upload_source=UploadSource.PERSONAL_CENTER,
        )
        report_image = ReportImage.objects.get(
            image_url=f"https://example.com/review-metric-{image_suffix}.png"
        )
        return CheckupResultValue.objects.create(
            patient=self.patient,
            report_image=report_image,
            checkup_item=self.checkup_item,
            standard_field=self.field_wbc,
            report_date=report_date,
            raw_name="白细胞计数",
            value_numeric=Decimal(str(value)),
            unit="10^9/L",
            abnormal_flag=abnormal_flag,
            **extra,
        )

    def _select_mapping(self):
        self.patient.indicator_preferences = {
            "followup_review": {"selected_mapping_ids": [self.mapping_wbc.id]}
        }
        self.patient.save(update_fields=["indicator_preferences"])


class HealthRecordsReviewMetricStatsTests(ReviewMetricTestBase):
    def setUp(self):
        super().setUp()
        self.url = reverse("web_patient:health_records")

    def test_stats_include_configured_metrics_with_latest_value_and_date_filter(self):
        order = self._create_paid_order(
            paid_at=timezone.now() - timedelta(days=10), duration_days=30
        )
        self._select_mapping()
        in_range_start = order.start_date + timedelta(days=1)
        self._create_result_value(
            in_range_start,
            "9.8",
            abnormal_flag=CheckupResultAbnormalFlag.NORMAL,
            image_suffix="early",
        )
        latest_date = order.start_date + timedelta(days=2)
        self._create_result_value(
            latest_date,
            "10.5",
            abnormal_flag=CheckupResultAbnormalFlag.HIGH,
            image_suffix="latest",
            lower_bound=Decimal("3.5"),
            upper_bound=Decimal("9.5"),
            range_text="3.5-9.5",
        )
        # 服务包范围外的记录不应计入统计
        self._create_result_value(
            order.start_date - timedelta(days=30),
            "5.1",
            abnormal_flag=CheckupResultAbnormalFlag.NORMAL,
            image_suffix="out-of-range",
        )

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

        stats = response.context["review_metric_stats"]
        self.assertEqual(len(stats), 1)
        item = stats[0]
        self.assertEqual(item["mapping_id"], self.mapping_wbc.id)
        self.assertEqual(item["title"], "白细胞计数(WBC)")
        self.assertEqual(item["category_name"], "血常规")
        self.assertEqual(item["count"], 2)
        self.assertEqual(item["latest_value"], "10.5")
        self.assertEqual(item["latest_unit"], "10^9/L")
        self.assertEqual(item["abnormal_flag"], CheckupResultAbnormalFlag.HIGH)
        self.assertEqual(response.context["active_tab"], "archive")

    def test_zero_record_metric_still_listed(self):
        self._create_paid_order(paid_at=timezone.now() - timedelta(days=10), duration_days=30)
        self._select_mapping()

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

        stats = response.context["review_metric_stats"]
        self.assertEqual(len(stats), 1)
        self.assertEqual(stats[0]["count"], 0)
        self.assertEqual(stats[0]["latest_value"], "")
        self.assertEqual(stats[0]["abnormal_flag"], "")

    def test_tab_param_controls_active_tab(self):
        self._create_paid_order(paid_at=timezone.now() - timedelta(days=10), duration_days=30)

        response = self.client.get(self.url, {"tab": "metrics"})
        self.assertEqual(response.context["active_tab"], "metrics")

        response = self.client.get(self.url, {"tab": "invalid"})
        self.assertEqual(response.context["active_tab"], "archive")

    def test_no_configured_metrics_returns_empty_stats(self):
        self._create_paid_order(paid_at=timezone.now() - timedelta(days=10), duration_days=30)

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["review_metric_stats"], [])

    def test_non_member_does_not_build_stats(self):
        self._select_mapping()

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["review_metric_stats"], [])


class HealthRecordsTabContentTests(ReviewMetricTestBase):
    """Tab 页内切换的局部内容接口测试。"""

    def setUp(self):
        super().setUp()
        self.url = reverse("web_patient:health_records_tab_content")
        self._create_paid_order(paid_at=timezone.now() - timedelta(days=10), duration_days=30)
        self._select_mapping()
        self._create_result_value(
            timezone.localdate() - timedelta(days=1),
            "10.5",
            abnormal_flag=CheckupResultAbnormalFlag.HIGH,
            image_suffix="tab-content",
            range_text="3.5-9.5",
        )

    def test_metrics_tab_returns_metric_cards(self):
        response = self.client.get(self.url, {"tab": "metrics"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_tab"], "metrics")
        self.assertTemplateUsed(response, "web_patient/partials/health_records_checkup_tabs.html")
        self.assertContains(response, "白细胞计数(WBC)")
        self.assertContains(response, "查看详情")

    def test_archive_tab_defaults_and_returns_archive_list(self):
        response = self.client.get(self.url, {"tab": "archive"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_tab"], "archive")
        self.assertContains(response, "血常规")

    def test_invalid_tab_falls_back_to_archive(self):
        response = self.client.get(self.url, {"tab": "invalid"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_tab"], "archive")

    def test_non_member_returns_empty_metrics_tab(self):
        other_user = CustomUser.objects.create_user(
            username="tabcontent_non_member",
            password="password",
            wx_openid="test_openid_tabcontent_non_member",
        )
        PatientProfile.objects.create(
            user=other_user, name="Non Member", phone="13900002003"
        )
        client = Client()
        client.force_login(other_user)

        response = client.get(self.url, {"tab": "metrics"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["review_metric_stats"], [])
        self.assertContains(response, "暂未配置关注指标")


class ReviewMetricDetailTests(ReviewMetricTestBase):
    def setUp(self):
        super().setUp()
        self._select_mapping()
        self.page_url = reverse("web_patient:review_metric_detail")
        self.api_url = reverse("web_patient:review_metric_detail_data")

    def test_detail_page_renders_records_and_chart(self):
        self._create_result_value(
            date(2025, 6, 10),
            "10.5",
            abnormal_flag=CheckupResultAbnormalFlag.HIGH,
            image_suffix="detail-a",
            range_text="3.5-9.5",
        )
        self._create_result_value(
            date(2025, 6, 3),
            "6.2",
            abnormal_flag=CheckupResultAbnormalFlag.NORMAL,
            image_suffix="detail-b",
        )

        response = self.client.get(
            self.page_url, {"mapping_id": self.mapping_wbc.id, "month": "2025-06"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["title"], "白细胞计数(WBC)")
        self.assertEqual(response.context["current_month"], "2025-06")
        self.assertTrue(response.context["chart_available"])

        items = response.context["initial_items"]
        self.assertEqual([item["date_str"] for item in items], ["2025-06-10", "2025-06-03"])
        self.assertEqual(items[0]["value"], "10.5")
        self.assertEqual(items[0]["abnormal_flag"], CheckupResultAbnormalFlag.HIGH)
        self.assertEqual(items[0]["source_label"], "患者上传")
        self.assertIn("3.5-9.5", items[0]["reference_range"])
        # 无 range_text 时用上下限拼装参考范围
        self.assertEqual(items[1]["reference_range"], "")
        self.assertContains(response, "白细胞计数(WBC)")

    def test_detail_page_initial_batch_anchors_month_and_fills_previous_month(self):
        # 锚定月之后的记录不应出现；锚定月不足时自动补前月数据（对齐一般监测）
        self._create_result_value(
            date(2025, 7, 1),
            "8.0",
            abnormal_flag=CheckupResultAbnormalFlag.NORMAL,
            image_suffix="anchor-after",
        )
        self._create_result_value(
            date(2025, 6, 10),
            "10.5",
            abnormal_flag=CheckupResultAbnormalFlag.HIGH,
            image_suffix="anchor-june",
        )
        self._create_result_value(
            date(2025, 5, 20),
            "6.2",
            abnormal_flag=CheckupResultAbnormalFlag.NORMAL,
            image_suffix="anchor-may",
        )

        response = self.client.get(
            self.page_url, {"mapping_id": self.mapping_wbc.id, "month": "2025-06"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["date_str"] for item in response.context["initial_items"]],
            ["2025-06-10", "2025-05-20"],
        )
        self.assertFalse(response.context["has_more"])
        self.assertIsNone(response.context["next_cursor_month"])
        self.assertTrue(response.context["has_records"])

    def test_same_date_records_keep_only_latest(self):
        # 同一日期多条结果仅展示最新写入的一条（id 最大，与图表口径一致）
        self._create_result_value(
            date(2025, 6, 10),
            "6.2",
            abnormal_flag=CheckupResultAbnormalFlag.NORMAL,
            image_suffix="dup-old",
        )
        self._create_result_value(
            date(2025, 6, 10),
            "10.5",
            abnormal_flag=CheckupResultAbnormalFlag.HIGH,
            image_suffix="dup-new",
        )

        response = self.client.get(
            self.page_url, {"mapping_id": self.mapping_wbc.id, "month": "2025-06"}
        )
        self.assertEqual(response.status_code, 200)
        items = response.context["initial_items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["value"], "10.5")
        self.assertEqual(items[0]["abnormal_flag"], CheckupResultAbnormalFlag.HIGH)

        api_response = self.client.get(
            self.api_url,
            {
                "mapping_id": self.mapping_wbc.id,
                "patient_id": self.patient.id,
                "cursor_month": "2025-06",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        payload = api_response.json()
        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(payload["items"][0]["value"], "10.5")
        self.assertFalse(payload["has_more"])

    def test_cursor_batch_counts_deduplicated_records(self):
        # 去重后游标分批按去重后条数计算
        self._create_result_value(
            date(2025, 6, 10),
            "6.2",
            abnormal_flag=CheckupResultAbnormalFlag.NORMAL,
            image_suffix="batch-dup-old",
        )
        self._create_result_value(
            date(2025, 6, 10),
            "10.5",
            abnormal_flag=CheckupResultAbnormalFlag.HIGH,
            image_suffix="batch-dup-new",
        )
        self._create_result_value(
            date(2025, 6, 5),
            "7.1",
            abnormal_flag=CheckupResultAbnormalFlag.NORMAL,
            image_suffix="batch-single",
        )

        first = self.client.get(
            self.api_url,
            {
                "mapping_id": self.mapping_wbc.id,
                "patient_id": self.patient.id,
                "cursor_month": "2025-06",
                "cursor_offset": 0,
                "limit": 1,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        payload = first.json()
        self.assertEqual([item["value"] for item in payload["items"]], ["10.5"])
        self.assertTrue(payload["has_more"])
        self.assertEqual(payload["next_cursor_month"], "2025-06")
        self.assertEqual(payload["next_cursor_offset"], 1)

        second = self.client.get(
            self.api_url,
            {
                "mapping_id": self.mapping_wbc.id,
                "patient_id": self.patient.id,
                "cursor_month": payload["next_cursor_month"],
                "cursor_offset": payload["next_cursor_offset"],
                "limit": 1,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        payload = second.json()
        self.assertEqual([item["value"] for item in payload["items"]], ["7.1"])
        self.assertFalse(payload["has_more"])

    def test_detail_page_invalid_mapping_returns_404(self):
        response = self.client.get(self.page_url, {"mapping_id": "999999"})
        self.assertEqual(response.status_code, 404)

    def test_data_api_month_returns_chart_payload(self):
        self._create_result_value(
            date(2025, 6, 10),
            "10.5",
            abnormal_flag=CheckupResultAbnormalFlag.HIGH,
            image_suffix="chart-a",
        )

        response = self.client.get(
            self.api_url,
            {"mapping_id": self.mapping_wbc.id, "month": "2025-06"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["month"], "2025-06")
        chart = payload["chart"]
        self.assertTrue(chart["has_data"])
        self.assertEqual(len(chart["data"]), 30)
        self.assertEqual(chart["data"][9], 10.5)
        self.assertEqual(chart["unit"], "10^9/L")

    def test_data_api_list_defaults_to_current_month_cursor(self):
        self._create_result_value(
            date(2025, 6, 10),
            "10.5",
            abnormal_flag=CheckupResultAbnormalFlag.HIGH,
            image_suffix="list-a",
            lower_bound=Decimal("3.5"),
            upper_bound=Decimal("9.5"),
        )
        self._create_result_value(
            date(2025, 5, 2),
            "6.2",
            abnormal_flag=CheckupResultAbnormalFlag.NORMAL,
            image_suffix="list-b",
        )

        response = self.client.get(
            self.api_url,
            {"mapping_id": self.mapping_wbc.id, "patient_id": self.patient.id},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        # 默认从当前月起倒序游标加载，当月不足自动补前月记录
        self.assertEqual(
            [item["date_str"] for item in payload["items"]],
            ["2025-06-10", "2025-05-02"],
        )
        self.assertFalse(payload["has_more"])
        self.assertIsNone(payload["next_cursor_month"])
        # 无 range_text 时用 lower_bound~upper_bound 拼装
        self.assertIn("3.5 ~ 9.5", payload["items"][0]["reference_range"])

    def test_data_api_list_cursor_batch_continues_within_month(self):
        for day, value, suffix in ((10, "10.5", "cursor-a"), (5, "6.2", "cursor-b"), (2, "7.1", "cursor-c")):
            self._create_result_value(
                date(2025, 6, day),
                value,
                abnormal_flag=CheckupResultAbnormalFlag.NORMAL,
                image_suffix=suffix,
            )

        first = self.client.get(
            self.api_url,
            {
                "mapping_id": self.mapping_wbc.id,
                "patient_id": self.patient.id,
                "cursor_month": "2025-06",
                "cursor_offset": 0,
                "limit": 2,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        payload = first.json()
        self.assertTrue(payload["success"])
        self.assertEqual(
            [item["date_str"] for item in payload["items"]],
            ["2025-06-10", "2025-06-05"],
        )
        self.assertTrue(payload["has_more"])
        self.assertEqual(payload["next_cursor_month"], "2025-06")
        self.assertEqual(payload["next_cursor_offset"], 2)
        self.assertEqual(payload["batch_size"], 2)

        second = self.client.get(
            self.api_url,
            {
                "mapping_id": self.mapping_wbc.id,
                "patient_id": self.patient.id,
                "cursor_month": payload["next_cursor_month"],
                "cursor_offset": payload["next_cursor_offset"],
                "limit": 2,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        payload = second.json()
        self.assertEqual(
            [item["date_str"] for item in payload["items"]],
            ["2025-06-02"],
        )
        self.assertFalse(payload["has_more"])
        self.assertIsNone(payload["next_cursor_month"])

    def test_data_api_rejects_patient_id_mismatch(self):
        other_user = CustomUser.objects.create_user(
            username="other_patient_review_metrics",
            password="password",
            wx_openid="test_openid_other_review_metrics",
        )
        other_patient = PatientProfile.objects.create(
            user=other_user, name="Other Patient", phone="13900002002"
        )

        response = self.client.get(
            self.api_url,
            {"mapping_id": self.mapping_wbc.id, "patient_id": other_patient.id},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 403)

    def test_data_api_invalid_mapping_returns_404(self):
        response = self.client.get(
            self.api_url,
            {"mapping_id": "999999"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 404)
