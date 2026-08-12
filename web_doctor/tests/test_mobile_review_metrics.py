"""医生端复查指标模块测试：健康档案 Tab、详情页与数据接口。"""

from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
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
from users import choices
from users.models import CustomUser, DoctorProfile, PatientProfile


class DoctorReviewMetricTestBase(TestCase):
    """医生端复查指标测试公共基类。"""

    def setUp(self):
        self.doctor_user = CustomUser.objects.create_user(
            username="doctor_review_metrics",
            password="password",
            user_type=choices.UserType.DOCTOR,
            phone="13900139201",
        )
        self.doctor_profile = DoctorProfile.objects.create(
            user=self.doctor_user,
            name="Dr. Review Metrics",
        )
        self.doctor_user.doctor_profile = self.doctor_profile
        self.doctor_user.save()

        self.patient_user = CustomUser.objects.create_user(
            username="patient_review_metrics_doctor_side",
            password="password",
            user_type=choices.UserType.PATIENT,
            phone="13800139201",
            wx_openid="wx_doctor_review_metrics",
        )
        self.patient = PatientProfile.objects.create(
            user=self.patient_user,
            name="复查指标患者",
            phone="13700139201",
            doctor=self.doctor_profile,
        )

        self.checkup_item = CheckupLibrary.objects.create(
            name="血常规",
            code="DOCTOR_REVIEW_METRIC_BLOOD_ROUTINE",
        )
        self.field_wbc = StandardField.objects.create(
            local_code="DOCTOR_REVIEW_METRIC_WBC",
            english_abbr="WBC",
            chinese_name="白细胞计数",
            value_type=StandardFieldValueType.DECIMAL,
            default_unit="10^9/L",
        )
        self.mapping_wbc = CheckupFieldMapping.objects.create(
            checkup_item=self.checkup_item,
            standard_field=self.field_wbc,
        )

        self.health_records_url = reverse("web_doctor:mobile_health_records")
        self.tab_content_url = reverse("web_doctor:mobile_health_records_tab_content")
        self.detail_url = reverse("web_doctor:mobile_review_metric_detail")
        self.data_url = reverse("web_doctor:mobile_review_metric_detail_data")
        self.client.force_login(self.doctor_user)

    def _create_paid_order(self, *, paid_at, duration_days):
        """创建一个有效服务包订单。

        Args:
            paid_at: 订单支付时间。
            duration_days: 服务包持续天数。

        Returns:
            Order: 已支付的订单对象。
        """
        product = Product.objects.create(
            name="医生端复查指标测试服务包",
            price=Decimal("199.00"),
            duration_days=duration_days,
        )
        return Order.objects.create(
            patient=self.patient,
            product=product,
            amount=Decimal("199.00"),
            status=Order.Status.PAID,
            paid_at=paid_at,
        )

    def _create_result_value(self, report_date, value, *, abnormal_flag, image_suffix, **extra):
        """创建一条带报告图片的结构化复查结果。

        Args:
            report_date: 结果所属的报告日期。
            value: 结果数值。
            abnormal_flag: 异常标记。
            image_suffix: 图片 URL 后缀，用于唯一标识图片。
            **extra: 透传到 `CheckupResultValue.objects.create()` 的额外字段。

        Returns:
            CheckupResultValue: 新建的结构化结果对象。
        """
        ReportUploadService.create_upload(
            self.patient,
            images=[
                {
                    "image_url": f"https://example.com/doctor-review-metric-{image_suffix}.png",
                    "record_type": ReportImage.RecordType.CHECKUP,
                    "checkup_item_id": self.checkup_item.id,
                    "report_date": report_date,
                }
            ],
            upload_source=UploadSource.PERSONAL_CENTER,
        )
        report_image = ReportImage.objects.get(
            image_url=f"https://example.com/doctor-review-metric-{image_suffix}.png"
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
        """为患者配置医生关注的复查指标。

        Returns:
            None: 该方法仅更新患者配置，不返回结果。
        """
        self.patient.indicator_preferences = {
            "followup_review": {"selected_mapping_ids": [self.mapping_wbc.id]}
        }
        self.patient.save(update_fields=["indicator_preferences"])


class MobileHealthRecordsReviewMetricTests(DoctorReviewMetricTestBase):
    """医生端健康档案页复查指标相关测试。"""

    def test_health_records_metrics_tab_shows_configured_metric_stats(self):
        order = self._create_paid_order(
            paid_at=timezone.now() - timedelta(days=10),
            duration_days=30,
        )
        self._select_mapping()
        self._create_result_value(
            order.start_date + timedelta(days=1),
            "10.5",
            abnormal_flag=CheckupResultAbnormalFlag.HIGH,
            image_suffix="stats",
        )

        response = self.client.get(
            self.health_records_url,
            {"patient_id": self.patient.id, "tab": "metrics"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_tab"], "metrics")
        self.assertEqual(len(response.context["review_metric_stats"]), 1)
        self.assertContains(response, "白细胞计数(WBC)")
        self.assertContains(
            response,
            reverse("web_doctor:mobile_review_metric_detail"),
        )

    def test_health_records_tab_content_returns_metrics_partial(self):
        self._create_paid_order(
            paid_at=timezone.now() - timedelta(days=10),
            duration_days=30,
        )
        self._select_mapping()
        self._create_result_value(
            timezone.localdate() - timedelta(days=1),
            "9.2",
            abnormal_flag=CheckupResultAbnormalFlag.NORMAL,
            image_suffix="partial",
        )

        response = self.client.get(
            self.tab_content_url,
            {"patient_id": self.patient.id, "tab": "metrics"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_tab"], "metrics")
        self.assertTemplateUsed(
            response,
            "web_doctor/mobile/partials/health_records_checkup_tabs.html",
        )
        self.assertContains(response, "白细胞计数(WBC)")

    def test_health_records_metrics_count_deduplicates_same_day_records(self):
        order = self._create_paid_order(
            paid_at=timezone.now() - timedelta(days=10),
            duration_days=30,
        )
        self._select_mapping()
        duplicated_date = order.start_date + timedelta(days=1)
        self._create_result_value(
            duplicated_date,
            "6.2",
            abnormal_flag=CheckupResultAbnormalFlag.NORMAL,
            image_suffix="same-day-old",
        )
        self._create_result_value(
            duplicated_date,
            "10.5",
            abnormal_flag=CheckupResultAbnormalFlag.HIGH,
            image_suffix="same-day-new",
        )
        self._create_result_value(
            order.start_date + timedelta(days=2),
            "7.1",
            abnormal_flag=CheckupResultAbnormalFlag.NORMAL,
            image_suffix="next-day",
        )

        response = self.client.get(
            self.health_records_url,
            {"patient_id": self.patient.id, "tab": "metrics"},
        )

        self.assertEqual(response.status_code, 200)
        stats = response.context["review_metric_stats"]
        self.assertEqual(len(stats), 1)
        self.assertEqual(stats[0]["count"], 2)
        self.assertEqual(stats[0]["latest_value"], "7.1")

    def test_health_records_metrics_tab_without_configuration_shows_empty_state(self):
        self._create_paid_order(
            paid_at=timezone.now() - timedelta(days=10),
            duration_days=30,
        )

        response = self.client.get(
            self.tab_content_url,
            {"patient_id": self.patient.id, "tab": "metrics"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["review_metric_stats"], [])
        self.assertContains(response, "暂未配置关注指标")


class MobileReviewMetricDetailTests(DoctorReviewMetricTestBase):
    """医生端复查指标详情页与接口测试。"""

    def setUp(self):
        super().setUp()
        self._select_mapping()

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
            self.detail_url,
            {
                "patient_id": self.patient.id,
                "mapping_id": self.mapping_wbc.id,
                "month": "2025-06",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["title"], "白细胞计数(WBC)")
        self.assertEqual(response.context["current_month"], "2025-06")
        self.assertTrue(response.context["chart_available"])
        self.assertEqual(
            [item["date_str"] for item in response.context["initial_items"]],
            ["2025-06-10", "2025-06-03"],
        )
        self.assertContains(response, "window.location.replace(url.toString())")
        self.assertContains(response, 'id="empty-state"')
        self.assertContains(response, "暂无记录")
        self.assertNotContains(response, "function resetListForMonth()")
        self.assertNotContains(response, "function refreshChartForMonth(")

    def test_detail_page_invalid_mapping_returns_404(self):
        response = self.client.get(
            self.detail_url,
            {"patient_id": self.patient.id, "mapping_id": "999999"},
        )
        self.assertEqual(response.status_code, 404)

    def test_detail_page_empty_state_matches_general_monitoring_style(self):
        response = self.client.get(
            self.detail_url,
            {
                "patient_id": self.patient.id,
                "mapping_id": self.mapping_wbc.id,
                "month": "2025-06",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["has_records"])
        self.assertContains(response, 'id="empty-state"')
        self.assertContains(response, "暂无记录")

    def test_data_api_month_returns_chart_payload(self):
        self._create_result_value(
            date(2025, 6, 10),
            "10.5",
            abnormal_flag=CheckupResultAbnormalFlag.HIGH,
            image_suffix="chart",
        )

        response = self.client.get(
            self.data_url,
            {
                "patient_id": self.patient.id,
                "mapping_id": self.mapping_wbc.id,
                "month": "2025-06",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["month"], "2025-06")
        self.assertTrue(payload["chart"]["has_data"])
        self.assertEqual(payload["chart"]["data"][9], 10.5)

    def test_data_api_cursor_returns_list_payload(self):
        self._create_result_value(
            date(2025, 6, 10),
            "10.5",
            abnormal_flag=CheckupResultAbnormalFlag.HIGH,
            image_suffix="cursor-a",
        )
        self._create_result_value(
            date(2025, 6, 5),
            "6.2",
            abnormal_flag=CheckupResultAbnormalFlag.NORMAL,
            image_suffix="cursor-b",
        )

        response = self.client.get(
            self.data_url,
            {
                "patient_id": self.patient.id,
                "mapping_id": self.mapping_wbc.id,
                "cursor_month": "2025-06",
                "cursor_offset": 0,
                "limit": 1,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual([item["date_str"] for item in payload["items"]], ["2025-06-10"])
        self.assertTrue(payload["has_more"])
        self.assertEqual(payload["next_cursor_month"], "2025-06")
        self.assertEqual(payload["next_cursor_offset"], 1)

    def test_data_api_invalid_cursor_offset_returns_400(self):
        response = self.client.get(
            self.data_url,
            {
                "patient_id": self.patient.id,
                "mapping_id": self.mapping_wbc.id,
                "cursor_month": "2025-06",
                "cursor_offset": "invalid",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
