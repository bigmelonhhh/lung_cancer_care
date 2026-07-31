from datetime import datetime, time
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import TreatmentCycle
from core.models import choices as core_choices
from health_data.models import (
    HealthMetric,
    MetricMeasurementContext,
    MetricSource,
    MetricType,
)
from users.models import CustomUser, PatientProfile


class HealthCalendarGeneralMonitoringMetricTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username="calendar_general_monitoring_patient",
            password="password",
            wx_openid="calendar_general_monitoring_openid",
        )
        self.patient = PatientProfile.objects.create(
            user=self.user,
            name="日历监测患者",
        )
        self.client.force_login(self.user)
        self.target_date = timezone.localdate()
        TreatmentCycle.objects.create(
            patient=self.patient,
            name="当前疗程",
            start_date=self.target_date,
            end_date=self.target_date,
            status=core_choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        self.calendar_url = reverse("web_patient:health_calendar")

    def _get_calendar(self):
        return self.client.get(
            self.calendar_url,
            {"date": self.target_date.isoformat()},
        )

    @patch("web_patient.views.health_calendar.get_daily_plan_summary")
    def test_metric_type_has_priority_and_new_cards_keep_home_order(self, mock_summary):
        mock_summary.return_value = [
            {
                "title": "无意义标题三",
                "metric_type": MetricType.URIC_ACID,
                "status": core_choices.TaskStatus.PENDING,
                "task_type": core_choices.PlanItemCategory.MONITORING,
            },
            {
                "title": "无意义标题一",
                "metric_type": MetricType.BLOOD_GLUCOSE,
                "status": core_choices.TaskStatus.PENDING,
                "task_type": core_choices.PlanItemCategory.MONITORING,
            },
            {
                "title": "无意义标题二",
                "metric_type": MetricType.BLOOD_KETONE,
                "status": core_choices.TaskStatus.PENDING,
                "task_type": core_choices.PlanItemCategory.MONITORING,
            },
        ]

        response = self._get_calendar()

        self.assertEqual(response.status_code, 200)
        plans = response.context["daily_plans"]
        self.assertEqual(
            [plan["type"] for plan in plans],
            ["glucose", "ketone", "uric_acid"],
        )
        self.assertEqual(
            [plan["title"] for plan in plans],
            ["血糖监测", "血酮监测", "尿酸监测"],
        )
        self.assertEqual(
            [plan["subtitle"] for plan in plans],
            ["请记录血糖", "请记录血酮", "请记录尿酸"],
        )
        for slug in ("glucose", "ketone", "uric_acid"):
            with self.subTest(slug=slug):
                self.assertEqual(
                    response.context["menuUrl"][slug],
                    f"{reverse('web_patient:record_general_monitoring', args=[slug])}"
                    "?source=calendar",
                )

    @patch("web_patient.views.health_calendar.get_daily_plan_summary")
    def test_new_cards_fallback_to_legacy_titles(self, mock_summary):
        mock_summary.return_value = [
            {
                "title": title,
                "status": core_choices.TaskStatus.PENDING,
                "task_type": core_choices.PlanItemCategory.MONITORING,
            }
            for title in ("尿酸监测", "血糖监测", "血酮监测")
        ]

        response = self._get_calendar()

        self.assertEqual(
            [plan["type"] for plan in response.context["daily_plans"]],
            ["glucose", "ketone", "uric_acid"],
        )

    @patch("web_patient.views.health_calendar.get_daily_plan_summary")
    def test_completed_cards_show_selected_date_values_context_and_units(
        self, mock_summary
    ):
        mock_summary.return_value = [
            {
                "title": definition[0],
                "metric_type": definition[1],
                "status": core_choices.TaskStatus.COMPLETED,
                "task_type": core_choices.PlanItemCategory.MONITORING,
            }
            for definition in (
                ("血糖监测", MetricType.BLOOD_GLUCOSE),
                ("血酮监测", MetricType.BLOOD_KETONE),
                ("尿酸监测", MetricType.URIC_ACID),
            )
        ]
        measured_at = timezone.make_aware(
            datetime.combine(self.target_date, time(hour=8))
        )
        for metric_type, value, measurement_context in (
            (
                MetricType.BLOOD_GLUCOSE,
                Decimal("6.2"),
                MetricMeasurementContext.FASTING,
            ),
            (MetricType.BLOOD_KETONE, Decimal("0.5"), None),
            (MetricType.URIC_ACID, Decimal("380"), None),
        ):
            HealthMetric.objects.create(
                patient=self.patient,
                metric_type=metric_type,
                value_main=value,
                measurement_context=measurement_context,
                measured_at=measured_at,
                source=MetricSource.MANUAL,
            )

        response = self._get_calendar()

        plans_by_type = {
            plan["type"]: plan for plan in response.context["daily_plans"]
        }
        self.assertEqual(
            plans_by_type["glucose"]["subtitle"],
            "已记录：空腹 6.2 mmol/L",
        )
        self.assertEqual(
            plans_by_type["ketone"]["subtitle"],
            "已记录：0.5 mmol/L",
        )
        self.assertEqual(
            plans_by_type["uric_acid"]["subtitle"],
            "已记录：380 μmol/L",
        )

    @patch("web_patient.views.health_calendar.get_daily_plan_summary")
    def test_stale_pending_cache_cannot_downgrade_completed_metric(
        self, mock_summary
    ):
        mock_summary.return_value = [
            {
                "title": "血糖监测",
                "metric_type": MetricType.BLOOD_GLUCOSE,
                "status": core_choices.TaskStatus.COMPLETED,
                "task_type": core_choices.PlanItemCategory.MONITORING,
            }
        ]
        measured_at = timezone.make_aware(
            datetime.combine(self.target_date, time(hour=9))
        )
        HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BLOOD_GLUCOSE,
            value_main=Decimal("6.8"),
            measurement_context=MetricMeasurementContext.RANDOM,
            measured_at=measured_at,
            source=MetricSource.MANUAL,
        )
        session = self.client.session
        session["metric_plan_cache"] = {
            self.target_date.isoformat(): {
                "glucose": {
                    "status": "pending",
                    "subtitle": "请记录血糖",
                }
            }
        }
        session.save()

        response = self._get_calendar()

        plan = response.context["daily_plans"][0]
        self.assertEqual(plan["status"], "completed")
        self.assertEqual(plan["subtitle"], "已记录：随机 6.8 mmol/L")
