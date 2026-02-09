from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from health_data.models import HealthMetric, MetricType
from market.models import Order, Product
from users import choices as user_choices
from users.models import CustomUser, PatientProfile


class HealthCalendarTaskTypeSkipMetricTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username="calendar_tasktype_user",
            password="password",
            user_type=user_choices.UserType.PATIENT,
            wx_openid="openid_calendar_tasktype_user",
        )
        self.patient = PatientProfile.objects.create(
            user=self.user,
            name="日历患者",
            phone="13800000021",
        )
        product = Product.objects.create(
            name="VIP 服务包", price=Decimal("199.00"), duration_days=30, is_active=True
        )
        Order.objects.create(
            patient=self.patient,
            product=product,
            amount=Decimal("199.00"),
            status=Order.Status.PAID,
            paid_at=timezone.now(),
        )
        self.client.force_login(self.user)
        self.calendar_url = reverse("web_patient:health_calendar")
        self.today = timezone.localdate().strftime("%Y-%m-%d")

    @patch("web_patient.views.health_calendar.get_daily_plan_summary")
    @patch("web_patient.views.health_calendar.HealthMetric.objects.filter")
    def test_task_type_checkup_and_questionnaire_skip_metric_query(
        self, mock_filter, mock_summary
    ):
        mock_filter.side_effect = AssertionError("should not query metric for 2/3 only")
        mock_summary.return_value = [
            {"title": "复查提醒", "status": 0, "task_type": 2},
            {"title": "问卷提醒", "status": 1, "task_type": 3, "questionnaire_ids": [6, 7, 5]},
        ]
        resp = self.client.get(f"{self.calendar_url}?date={self.today}&ajax=1")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode("utf-8")
        self.assertIn("复查提醒", html)
        self.assertIn("问卷提醒", html)
        self.assertIn("未完成", html)
        self.assertIn("已完成", html)

    @patch("web_patient.views.health_calendar.get_daily_plan_summary")
    def test_other_task_types_still_use_metric_query_for_display(self, mock_summary):
        mock_summary.return_value = [
            {"title": "体温", "status": 1, "task_type": 4},
        ]
        measured_at = timezone.make_aware(
            datetime.combine(timezone.localdate(), datetime.min.time())
        )
        HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BODY_TEMPERATURE,
            value_main=Decimal("36.5"),
            measured_at=measured_at,
            source="manual",
        )
        resp = self.client.get(f"{self.calendar_url}?date={self.today}&ajax=1")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode("utf-8")
        self.assertIn("已记录", html)
        self.assertIn("36.5", html)
