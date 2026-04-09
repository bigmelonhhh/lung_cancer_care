from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import CheckupLibrary, QuestionnaireCode
from health_data.models import HealthMetric, MetricSource, MetricType, ReportImage, UploadSource
from health_data.services.report_service import ReportUploadService
from market.models import Order, Product
from patient_alerts.models import AlertEventType, AlertLevel, PatientAlert
from users import choices
from users.models import DoctorProfile, PatientProfile

User = get_user_model()


class MobileHealthRecordsStatsTests(TestCase):
    def setUp(self):
        self.doctor_user = User.objects.create_user(
            username="doc_health_records_stats",
            password="password",
            user_type=choices.UserType.DOCTOR,
            phone="13900139101",
        )
        self.doctor_profile = DoctorProfile.objects.create(
            user=self.doctor_user,
            name="Dr. Health Stats",
        )
        self.doctor_user.doctor_profile = self.doctor_profile
        self.doctor_user.save()

        self.patient_user = User.objects.create_user(
            username="patient_health_records_stats",
            password="password",
            user_type=choices.UserType.PATIENT,
            phone="13800139101",
            wx_openid="wx_health_records_stats",
        )
        self.patient = PatientProfile.objects.create(
            user=self.patient_user,
            name="统计患者",
            phone="13700139101",
            doctor=self.doctor_profile,
        )

        self.product = Product.objects.create(
            name="VIP 服务包",
            price=Decimal("199.00"),
            duration_days=30,
            is_active=True,
        )
        self.order = Order.objects.create(
            patient=self.patient,
            product=self.product,
            amount=Decimal("199.00"),
            status=Order.Status.PAID,
            paid_at=timezone.now(),
        )

        self.checkup_item = CheckupLibrary.objects.create(
            name="血常规",
            code="BLOOD_ROUTINE",
            is_active=True,
        )

        self.doctor_url = reverse("web_doctor:mobile_health_records")
        self.patient_url = reverse("web_patient:health_records")

    def _make_aware(self, target_date, hour=9, minute=0):
        return timezone.make_aware(datetime.combine(target_date, time(hour, minute)))

    def _create_metric_alert(self, metric_type, event_time):
        PatientAlert.objects.create(
            patient=self.patient,
            doctor=self.doctor_profile,
            event_type=AlertEventType.DATA,
            event_level=AlertLevel.MILD,
            event_title="指标异常",
            event_content="测试指标异常",
            event_time=event_time,
            source_type="metric",
            source_payload={"metric_type": metric_type},
        )

    def _create_questionnaire_alert(self, questionnaire_code, event_time):
        PatientAlert.objects.create(
            patient=self.patient,
            doctor=self.doctor_profile,
            event_type=AlertEventType.QUESTIONNAIRE,
            event_level=AlertLevel.MODERATE,
            event_title="问卷异常",
            event_content="测试问卷异常",
            event_time=event_time,
            source_type="questionnaire",
            source_payload={"questionnaire_code": questionnaire_code},
        )

    def test_mobile_health_records_shows_metric_count_and_abnormal(self):
        measured_at = self._make_aware(self.order.start_date, hour=10)
        HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BODY_TEMPERATURE,
            source=MetricSource.MANUAL,
            value_main=Decimal("38.20"),
            measured_at=measured_at,
        )
        self._create_metric_alert(
            MetricType.BODY_TEMPERATURE,
            self._make_aware(self.order.start_date, hour=11),
        )

        self.client.force_login(self.doctor_user)
        response = self.client.get(f"{self.doctor_url}?patient_id={self.patient.id}")

        self.assertEqual(response.status_code, 200)
        temp_stat = next(
            item for item in response.context["health_stats"] if item["type"] == "temperature"
        )
        self.assertEqual(temp_stat["count"], 1)
        self.assertEqual(temp_stat["abnormal"], 1)
        self.assertContains(response, "记录：1次")
        self.assertContains(response, "异常：1次")

    def test_mobile_health_records_shows_questionnaire_count_and_abnormal(self):
        measured_at = self._make_aware(self.order.start_date, hour=12)
        HealthMetric.objects.create(
            patient=self.patient,
            metric_type=QuestionnaireCode.Q_COUGH,
            source=MetricSource.MANUAL,
            value_main=Decimal("6.00"),
            measured_at=measured_at,
        )
        self._create_questionnaire_alert(
            QuestionnaireCode.Q_COUGH,
            self._make_aware(self.order.start_date, hour=13),
        )

        self.client.force_login(self.doctor_user)
        response = self.client.get(f"{self.doctor_url}?patient_id={self.patient.id}")

        self.assertEqual(response.status_code, 200)
        cough_stat = next(
            item for item in response.context["health_survey_stats"] if item["type"] == "cough"
        )
        self.assertEqual(cough_stat["count"], 1)
        self.assertEqual(cough_stat["abnormal"], 1)

    def test_mobile_health_records_counts_checkup_only_within_service_package_range(self):
        in_range_date = min(self.order.end_date, self.order.start_date + timedelta(days=1))
        out_of_range_date = self.order.start_date - timedelta(days=1)

        ReportUploadService.create_upload(
            self.patient,
            images=[
                {
                    "image_url": "https://example.com/in-range.png",
                    "record_type": ReportImage.RecordType.CHECKUP,
                    "checkup_item_id": self.checkup_item.id,
                    "report_date": in_range_date,
                }
            ],
            upload_source=UploadSource.CHECKUP_PLAN,
        )
        ReportUploadService.create_upload(
            self.patient,
            images=[
                {
                    "image_url": "https://example.com/out-range.png",
                    "record_type": ReportImage.RecordType.CHECKUP,
                    "checkup_item_id": self.checkup_item.id,
                    "report_date": out_of_range_date,
                }
            ],
            upload_source=UploadSource.CHECKUP_PLAN,
        )

        self.client.force_login(self.doctor_user)
        response = self.client.get(f"{self.doctor_url}?patient_id={self.patient.id}")

        self.assertEqual(response.status_code, 200)
        checkup_stat = next(
            item for item in response.context["checkup_stats"] if item["code"] == self.checkup_item.code
        )
        self.assertEqual(checkup_stat["count"], 1)

    def test_mobile_health_records_non_member_keeps_general_stats_and_hides_member_sections(self):
        expired_paid_at = timezone.now() - timedelta(days=60)
        Order.objects.filter(id=self.order.id).update(paid_at=expired_paid_at)
        self.patient.refresh_from_db()

        measured_at = self._make_aware(timezone.localdate() - timedelta(days=1), hour=10)
        HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BODY_TEMPERATURE,
            source=MetricSource.MANUAL,
            value_main=Decimal("37.50"),
            measured_at=measured_at,
        )

        self.client.force_login(self.doctor_user)
        response = self.client.get(f"{self.doctor_url}?patient_id={self.patient.id}")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["is_member"])
        temp_stat = next(
            item for item in response.context["health_stats"] if item["type"] == "temperature"
        )
        self.assertEqual(temp_stat["count"], 1)
        self.assertEqual(response.context["health_survey_stats"], [])
        self.assertEqual(response.context["checkup_stats"], [])
        self.assertContains(response, 'id="survey-section" class="hidden"', html=False)
        self.assertContains(response, 'id="checkup-section" class="hidden"', html=False)

    def test_mobile_health_records_matches_patient_stats_for_same_service_package(self):
        measured_at = self._make_aware(self.order.start_date, hour=9)
        HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BODY_TEMPERATURE,
            source=MetricSource.MANUAL,
            value_main=Decimal("38.00"),
            measured_at=measured_at,
        )
        HealthMetric.objects.create(
            patient=self.patient,
            metric_type=QuestionnaireCode.Q_COUGH,
            source=MetricSource.MANUAL,
            value_main=Decimal("5.00"),
            measured_at=self._make_aware(self.order.start_date, hour=14),
        )
        self._create_metric_alert(
            MetricType.BODY_TEMPERATURE,
            self._make_aware(self.order.start_date, hour=10),
        )
        self._create_questionnaire_alert(
            QuestionnaireCode.Q_COUGH,
            self._make_aware(self.order.start_date, hour=15),
        )

        self.client.force_login(self.doctor_user)
        doctor_response = self.client.get(f"{self.doctor_url}?patient_id={self.patient.id}")
        self.assertEqual(doctor_response.status_code, 200)

        self.client.force_login(self.patient_user)
        patient_response = self.client.get(self.patient_url)
        self.assertEqual(patient_response.status_code, 200)

        doctor_general = {
            item["type"]: (item["count"], item["abnormal"])
            for item in doctor_response.context["health_stats"]
        }
        patient_general = {
            item["type"]: (item["count"], item["abnormal"])
            for item in patient_response.context["health_stats"]
        }
        self.assertEqual(doctor_general, patient_general)

        doctor_survey = {
            item["type"]: (item["count"], item["abnormal"])
            for item in doctor_response.context["health_survey_stats"]
        }
        patient_survey = {
            item["type"]: (item["count"], item["abnormal"])
            for item in patient_response.context["health_survey_stats"]
        }
        self.assertEqual(doctor_survey, patient_survey)
