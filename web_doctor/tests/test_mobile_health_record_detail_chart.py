from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import DailyTask, Questionnaire, QuestionnaireCode
from core.models.choices import PlanItemCategory, TaskStatus
from health_data.models import HealthMetric, MetricType
from users.models import DoctorProfile, PatientProfile

User = get_user_model()


class MobileHealthRecordDetailChartTests(TestCase):
    def setUp(self):
        self.doctor_user = User.objects.create_user(
            username="doc_chart_test",
            password="password",
            user_type=2,
            phone="13900139041",
        )
        self.doctor_profile = DoctorProfile.objects.create(
            user=self.doctor_user, name="Dr. Chart"
        )
        self.doctor_user.doctor_profile = self.doctor_profile
        self.doctor_user.save()

        self.patient = PatientProfile.objects.create(
            name="患者图表",
            phone="13800138241",
            doctor=self.doctor_profile,
        )

        self.client.force_login(self.doctor_user)
        self.url = reverse("web_doctor:mobile_health_record_detail")
        self.tz = timezone.get_current_timezone()

    def _aware_dt(self, year, month, day, hour=9, minute=0):
        return timezone.make_aware(datetime(year, month, day, hour, minute), self.tz)

    def _create_metric(
        self,
        *,
        metric_type,
        year,
        month,
        day,
        hour,
        minute=0,
        value_main="1",
        value_sub=None,
    ):
        return HealthMetric.objects.create(
            patient=self.patient,
            metric_type=metric_type,
            measured_at=self._aware_dt(year, month, day, hour, minute),
            value_main=Decimal(str(value_main)),
            value_sub=Decimal(str(value_sub)) if value_sub is not None else None,
            source="manual",
        )

    def test_temperature_page_has_chart_context_and_switch(self):
        response = self.client.get(
            self.url,
            {
                "type": "temperature",
                "title": "体温",
                "patient_id": self.patient.id,
                "month": "2025-03",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["chart_available"])
        self.assertEqual(response.context["chart_mode"], "line")
        self.assertContains(response, "切换图表")
        self.assertContains(response, 'id="record-chart-wrapper"')

    def test_medication_chart_payload_uses_all_completed_rule(self):
        DailyTask.objects.create(
            patient=self.patient,
            task_date=datetime(2025, 2, 2).date(),
            task_type=PlanItemCategory.MEDICATION,
            title="用药提醒",
            status=TaskStatus.COMPLETED,
        )
        DailyTask.objects.create(
            patient=self.patient,
            task_date=datetime(2025, 2, 3).date(),
            task_type=PlanItemCategory.MEDICATION,
            title="用药提醒",
            status=TaskStatus.COMPLETED,
        )
        DailyTask.objects.create(
            patient=self.patient,
            task_date=datetime(2025, 2, 3).date(),
            task_type=PlanItemCategory.MEDICATION,
            title="用药提醒",
            status=TaskStatus.PENDING,
        )

        response = self.client.get(
            self.url,
            {
                "type": "medical",
                "title": "用药",
                "patient_id": self.patient.id,
                "month": "2025-02",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.context["chart_payload"]
        status_map = {item["date"]: item["status"] for item in payload["items"]}
        self.assertEqual(status_map["02-01"], "none")
        self.assertEqual(status_map["02-02"], "completed")
        self.assertEqual(status_map["02-03"], "pending")
        self.assertEqual(response.context["chart_mode"], "medication_table")
        self.assertTrue(response.context["chart_available"])
        self.assertContains(response, "是否服药")

    def test_bp_chart_uses_latest_value_and_two_series(self):
        self._create_metric(
            metric_type=MetricType.BLOOD_PRESSURE,
            year=2025,
            month=3,
            day=10,
            hour=8,
            value_main="120",
            value_sub="80",
        )
        self._create_metric(
            metric_type=MetricType.BLOOD_PRESSURE,
            year=2025,
            month=3,
            day=10,
            hour=20,
            value_main="130",
            value_sub="85",
        )
        self._create_metric(
            metric_type=MetricType.BLOOD_PRESSURE,
            year=2025,
            month=3,
            day=12,
            hour=9,
            value_main="118",
            value_sub="78",
        )

        response = self.client.get(
            self.url,
            {
                "type": "bp",
                "title": "血压",
                "patient_id": self.patient.id,
                "month": "2025-03",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.context["chart_payload"]
        self.assertEqual(len(payload["series"]), 2)
        self.assertEqual(payload["series"][0]["name"], "收缩压")
        self.assertEqual(payload["series"][1]["name"], "舒张压")

        idx = payload["dates"].index("03-10")
        self.assertEqual(payload["series"][0]["data"][idx], 130)
        self.assertEqual(payload["series"][1]["data"][idx], 85)

        missing_idx = payload["dates"].index("03-11")
        self.assertEqual(payload["series"][0]["data"][missing_idx], 0)
        self.assertEqual(payload["series"][1]["data"][missing_idx], 0)

    def test_questionnaire_chart_marks_no_task_days(self):
        Questionnaire.objects.get_or_create(
            code=QuestionnaireCode.Q_ANXIETY,
            defaults={"name": "焦虑评估", "is_active": True},
        )

        self._create_metric(
            metric_type=QuestionnaireCode.Q_ANXIETY,
            year=2025,
            month=3,
            day=2,
            hour=9,
            value_main="0",
        )
        self._create_metric(
            metric_type=QuestionnaireCode.Q_ANXIETY,
            year=2025,
            month=3,
            day=3,
            hour=10,
            value_main="5",
        )

        DailyTask.objects.create(
            patient=self.patient,
            task_date=datetime(2025, 3, 2).date(),
            task_type=PlanItemCategory.QUESTIONNAIRE,
            title="焦虑评估",
            interaction_payload={"questionnaire_code": QuestionnaireCode.Q_ANXIETY},
        )
        DailyTask.objects.create(
            patient=self.patient,
            task_date=datetime(2025, 3, 3).date(),
            task_type=PlanItemCategory.QUESTIONNAIRE,
            title="焦虑评估",
            interaction_payload={"questionnaire_code": QuestionnaireCode.Q_ANXIETY},
        )

        with patch("web_doctor.views.mobile.health_record._is_member", return_value=True):
            response = self.client.get(
                self.url,
                {
                    "type": "anxiety",
                    "title": "焦虑评估",
                    "patient_id": self.patient.id,
                    "month": "2025-03",
                },
            )
        self.assertEqual(response.status_code, 200)
        payload = response.context["chart_payload"]
        series_data = payload["series"][0]["data"]

        day_1_idx = payload["dates"].index("03-01")
        day_2_idx = payload["dates"].index("03-02")
        day_3_idx = payload["dates"].index("03-03")

        self.assertEqual(series_data[day_1_idx]["value"], 0)
        self.assertIsNone(series_data[day_1_idx]["raw_value"])
        self.assertTrue(series_data[day_1_idx]["is_no_task"])

        self.assertEqual(series_data[day_2_idx]["value"], 0.0)
        self.assertEqual(series_data[day_2_idx]["raw_value"], 0.0)
        self.assertFalse(series_data[day_2_idx]["is_no_task"])

        self.assertEqual(series_data[day_3_idx]["value"], 5.0)
        self.assertEqual(series_data[day_3_idx]["raw_value"], 5.0)
        self.assertFalse(series_data[day_3_idx]["is_no_task"])

    def test_oral_mucosa_questionnaire_chart_marks_no_task_days(self):
        Questionnaire.objects.get_or_create(
            code=QuestionnaireCode.Q_KQNMLB,
            defaults={"name": "口腔黏膜损伤自评量表", "is_active": True},
        )

        self._create_metric(
            metric_type=QuestionnaireCode.Q_KQNMLB,
            year=2025,
            month=3,
            day=2,
            hour=9,
            value_main="0",
        )
        self._create_metric(
            metric_type=QuestionnaireCode.Q_KQNMLB,
            year=2025,
            month=3,
            day=3,
            hour=10,
            value_main="4",
        )

        DailyTask.objects.create(
            patient=self.patient,
            task_date=datetime(2025, 3, 2).date(),
            task_type=PlanItemCategory.QUESTIONNAIRE,
            title="口腔黏膜损伤自评量表",
            interaction_payload={"questionnaire_code": QuestionnaireCode.Q_KQNMLB},
        )
        DailyTask.objects.create(
            patient=self.patient,
            task_date=datetime(2025, 3, 3).date(),
            task_type=PlanItemCategory.QUESTIONNAIRE,
            title="口腔黏膜损伤自评量表",
            interaction_payload={"questionnaire_code": QuestionnaireCode.Q_KQNMLB},
        )

        with patch("web_doctor.views.mobile.health_record._is_member", return_value=True):
            response = self.client.get(
                self.url,
                {
                    "type": "oral_mucosa",
                    "title": "口腔黏膜损伤自评量表",
                    "patient_id": self.patient.id,
                    "month": "2025-03",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["is_questionnaire_type"])
        payload = response.context["chart_payload"]
        series_data = payload["series"][0]["data"]

        day_1_idx = payload["dates"].index("03-01")
        day_2_idx = payload["dates"].index("03-02")
        day_3_idx = payload["dates"].index("03-03")

        self.assertEqual(series_data[day_1_idx]["value"], 0)
        self.assertIsNone(series_data[day_1_idx]["raw_value"])
        self.assertTrue(series_data[day_1_idx]["is_no_task"])

        self.assertEqual(series_data[day_2_idx]["value"], 0.0)
        self.assertEqual(series_data[day_2_idx]["raw_value"], 0.0)
        self.assertFalse(series_data[day_2_idx]["is_no_task"])

        self.assertEqual(series_data[day_3_idx]["value"], 4.0)
        self.assertEqual(series_data[day_3_idx]["raw_value"], 4.0)
        self.assertFalse(series_data[day_3_idx]["is_no_task"])

    def test_month_boundary_excludes_next_month_midnight_data(self):
        self._create_metric(
            metric_type=MetricType.BODY_TEMPERATURE,
            year=2025,
            month=1,
            day=31,
            hour=23,
            minute=59,
            value_main="36.5",
        )
        self._create_metric(
            metric_type=MetricType.BODY_TEMPERATURE,
            year=2025,
            month=2,
            day=1,
            hour=0,
            minute=0,
            value_main="36.9",
        )

        response = self.client.get(
            self.url,
            {
                "type": "temperature",
                "title": "体温",
                "patient_id": self.patient.id,
                "month": "2025-01",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["records"]), 1)
        self.assertEqual(payload["records"][0]["date"], "2025-01-31")

    def test_empty_list_keeps_chart_switch_and_has_records_false(self):
        response = self.client.get(
            self.url,
            {
                "type": "temperature",
                "title": "体温",
                "patient_id": self.patient.id,
                "month": "2025-03",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "切换图表")
        self.assertContains(response, "const hasRecords = false;")
