from datetime import datetime, timedelta
from unittest.mock import patch

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import DailyTask, MonitoringTemplate, PlanItem, TreatmentCycle
from core.models import choices as core_choices
from health_data.models import (
    HealthMetric,
    MetricMeasurementContext,
    MetricType,
)
from users.models import CustomUser, PatientProfile


class HealthCalendarSelectedDateRecordingTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = CustomUser.objects.create_user(
            username="testpatient_calendar_selected_date",
            password="password",
            wx_openid="test_openid_calendar_selected_date",
        )
        self.patient = PatientProfile.objects.create(user=self.user, name="Test Patient")
        self.client.force_login(self.user)

    def test_record_pages_render_selected_date_in_datetime_local_value(self):
        selected_date = "2026-01-11"
        cases = [
            reverse("web_patient:record_temperature"),
            reverse("web_patient:record_bp"),
            reverse("web_patient:record_spo2"),
            reverse("web_patient:record_weight"),
            reverse(
                "web_patient:record_general_monitoring",
                args=["glucose"],
            ),
            reverse(
                "web_patient:record_general_monitoring",
                args=["ketone"],
            ),
            reverse(
                "web_patient:record_general_monitoring",
                args=["uric_acid"],
            ),
        ]
        for url in cases:
            resp = self.client.get(url, {"selected_date": selected_date})
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, f'value=\"{selected_date}T')

    def test_record_temperature_post_overrides_date_to_selected_date(self):
        selected_date = "2026-01-11"
        url = reverse("web_patient:record_temperature")
        resp = self.client.post(
            url,
            {
                "temperature": "36.5",
                "record_time": "2026-01-24 19:46",
                "record_time_touched": "1",
                "selected_date": selected_date,
            },
        )
        self.assertEqual(resp.status_code, 302)
        metric = HealthMetric.objects.filter(
            patient=self.patient, metric_type=MetricType.BODY_TEMPERATURE
        ).last()
        self.assertIsNotNone(metric)
        self.assertEqual(timezone.localtime(metric.measured_at).date().isoformat(), selected_date)

    def test_general_monitoring_posts_complete_selected_date_tasks_and_refresh_calendar(
        self,
    ):
        selected_date = timezone.localdate() - timedelta(days=1)
        cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="健康日历补录疗程",
            start_date=selected_date,
            end_date=timezone.localdate(),
            status=core_choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        cases = (
            (
                "glucose",
                MetricType.BLOOD_GLUCOSE,
                "血糖监测",
                "6.2",
                MetricMeasurementContext.FASTING,
            ),
            ("ketone", MetricType.BLOOD_KETONE, "血酮监测", "0.5", None),
            ("uric_acid", MetricType.URIC_ACID, "尿酸监测", "380", None),
        )
        task_ids = []
        for _slug, metric_type, title, _value, _context in cases:
            template, _ = MonitoringTemplate.objects.get_or_create(
                code=metric_type,
                defaults={
                    "name": title,
                    "metric_type": metric_type,
                    "is_active": True,
                },
            )
            plan_item = PlanItem.objects.create(
                cycle=cycle,
                category=core_choices.PlanItemCategory.MONITORING,
                template_id=template.id,
                item_name=title,
                schedule_days=[1],
                status=core_choices.PlanItemStatus.ACTIVE,
            )
            task_ids.append(
                DailyTask.objects.create(
                    patient=self.patient,
                    plan_item=plan_item,
                    task_date=selected_date,
                    task_type=core_choices.PlanItemCategory.MONITORING,
                    title=title,
                    status=core_choices.TaskStatus.PENDING,
                ).id
            )

        for slug, metric_type, _title, value, context in cases:
            form_data = {
                "value": value,
                "selected_date": selected_date.isoformat(),
                "record_time_touched": "0",
            }
            if context:
                form_data["measurement_context"] = context
            response = self.client.post(
                (
                    reverse(
                        "web_patient:record_general_monitoring",
                        args=[slug],
                    )
                    + "?source=calendar"
                ),
                form_data,
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "success")
            metric = HealthMetric.objects.get(
                patient=self.patient,
                metric_type=metric_type,
            )
            self.assertEqual(
                timezone.localtime(metric.measured_at).date(),
                selected_date,
            )

        self.assertEqual(
            DailyTask.objects.filter(
                id__in=task_ids,
                status=core_choices.TaskStatus.COMPLETED,
            ).count(),
            3,
        )

        calendar_response = self.client.get(
            reverse("web_patient:health_calendar"),
            {"date": selected_date.isoformat()},
        )
        self.assertEqual(calendar_response.status_code, 200)
        plans_by_type = {
            plan["type"]: plan for plan in calendar_response.context["daily_plans"]
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

    def test_record_bp_post_overrides_date_to_selected_date(self):
        selected_date = "2026-01-11"
        url = reverse("web_patient:record_bp")
        resp = self.client.post(
            url,
            {
                "ssy": "120",
                "szy": "80",
                "heart": "75",
                "record_time": "2026-01-24 19:46",
                "record_time_touched": "1",
                "selected_date": selected_date,
            },
        )
        self.assertEqual(resp.status_code, 302)
        bp_metric = HealthMetric.objects.filter(
            patient=self.patient, metric_type=MetricType.BLOOD_PRESSURE
        ).last()
        hr_metric = HealthMetric.objects.filter(
            patient=self.patient, metric_type=MetricType.HEART_RATE
        ).last()
        self.assertIsNotNone(bp_metric)
        self.assertIsNotNone(hr_metric)
        self.assertEqual(timezone.localtime(bp_metric.measured_at).date().isoformat(), selected_date)
        self.assertEqual(timezone.localtime(hr_metric.measured_at).date().isoformat(), selected_date)
        self.assertEqual(
            timezone.localtime(bp_metric.measured_at).strftime("%Y-%m-%d %H:%M"),
            "2026-01-11 19:46",
        )

    @patch("web_patient.views.record.timezone.now")
    def test_record_bp_selected_date_uses_submit_current_time_when_not_touched(
        self, mock_now
    ):
        selected_date = "2026-01-11"
        mock_now.return_value = timezone.make_aware(datetime(2026, 1, 24, 10, 5, 30))
        resp = self.client.post(
            reverse("web_patient:record_bp"),
            {
                "ssy": "120",
                "szy": "80",
                "heart": "75",
                "record_time": "2026-01-24 10:01",
                "record_time_touched": "0",
                "selected_date": selected_date,
            },
        )

        self.assertEqual(resp.status_code, 302)
        bp_metric = HealthMetric.objects.filter(
            patient=self.patient,
            metric_type=MetricType.BLOOD_PRESSURE,
        ).last()
        hr_metric = HealthMetric.objects.filter(
            patient=self.patient,
            metric_type=MetricType.HEART_RATE,
        ).last()
        self.assertEqual(
            timezone.localtime(bp_metric.measured_at).strftime("%Y-%m-%d %H:%M:%S"),
            "2026-01-11 10:05:30",
        )
        self.assertEqual(bp_metric.measured_at, hr_metric.measured_at)

    def test_record_spo2_post_overrides_date_to_selected_date(self):
        selected_date = "2026-01-11"
        url = reverse("web_patient:record_spo2")
        resp = self.client.post(
            url,
            {
                "spo2": "98",
                "record_time": "2026-01-24 19:46",
                "record_time_touched": "1",
                "selected_date": selected_date,
            },
        )
        self.assertEqual(resp.status_code, 302)
        metric = HealthMetric.objects.filter(
            patient=self.patient, metric_type=MetricType.BLOOD_OXYGEN
        ).last()
        self.assertIsNotNone(metric)
        self.assertEqual(timezone.localtime(metric.measured_at).date().isoformat(), selected_date)

    def test_record_weight_post_overrides_date_to_selected_date(self):
        selected_date = "2026-01-11"
        url = reverse("web_patient:record_weight")
        resp = self.client.post(
            url,
            {
                "weight": "60.0",
                "record_time": "2026-01-24 19:46",
                "record_time_touched": "1",
                "selected_date": selected_date,
            },
        )
        self.assertEqual(resp.status_code, 302)
        metric = HealthMetric.objects.filter(
            patient=self.patient, metric_type=MetricType.WEIGHT
        ).last()
        self.assertIsNotNone(metric)
        self.assertEqual(timezone.localtime(metric.measured_at).date().isoformat(), selected_date)

