from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import CheckupLibrary, Questionnaire, QuestionnaireCode
from health_data.models import (
    HealthMetric,
    MetricSource,
    MetricType,
    QuestionnaireSubmission,
    ReportImage,
    UploadSource,
)
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

    def _create_submission(self, questionnaire, score, submitted_at):
        submission = QuestionnaireSubmission.objects.create(
            patient=self.patient,
            questionnaire=questionnaire,
            total_score=Decimal(score),
        )
        QuestionnaireSubmission.objects.filter(pk=submission.pk).update(
            created_at=submitted_at
        )
        return submission

    def test_mobile_health_records_uses_dynamic_active_questionnaires_in_selected_package(self):
        active = Questionnaire.objects.create(
            name='生活质量评估 <script>alert("x")</script>',
            code="Q_MOBILE_DYNAMIC_ACTIVE",
            is_active=True,
            sort_order=1,
        )
        Questionnaire.objects.create(
            name="启用但无记录问卷",
            code="Q_MOBILE_DYNAMIC_EMPTY",
            is_active=True,
            sort_order=2,
        )
        inactive = Questionnaire.objects.create(
            name="停用问卷",
            code="Q_MOBILE_DYNAMIC_OFF",
            is_active=False,
            sort_order=3,
        )
        self._create_submission(
            active,
            "8",
            self._make_aware(self.order.start_date + timedelta(days=1)),
        )
        self._create_questionnaire_alert(
            active.code,
            self._make_aware(self.order.start_date + timedelta(days=1), hour=10),
        )
        self._create_submission(
            active,
            "3",
            self._make_aware(self.order.start_date - timedelta(days=1)),
        )
        self._create_submission(
            inactive,
            "5",
            self._make_aware(self.order.start_date + timedelta(days=2)),
        )

        self.client.force_login(self.doctor_user)
        response = self.client.get(
            self.doctor_url,
            {"patient_id": self.patient.id, "package_id": self.order.id},
        )

        self.assertEqual(response.status_code, 200)
        cards = response.context["health_survey_stats"]
        self.assertEqual([item["questionnaire_id"] for item in cards], [active.id])
        self.assertEqual(cards[0]["count"], 1)
        self.assertEqual(cards[0]["latest_score"], Decimal("8.00"))
        self.assertEqual(cards[0]["abnormal"], 1)
        self.assertContains(response, "生活质量评估 &lt;script&gt;")
        self.assertContains(response, "异常：")
        self.assertNotContains(response, "问卷评分：")
        self.assertNotContains(response, "启用但无记录问卷")
        self.assertNotContains(response, "停用问卷")
        self.assertContains(response, f"questionnaire_id={active.id}")
        self.assertContains(response, f"package_id={self.order.id}")

    def test_mobile_eqvas_card_does_not_display_latest_vas_score(self):
        eqvas = Questionnaire.objects.create(
            name="EQVAS量表",
            code="Q_EQVAS",
            is_active=True,
            sort_order=1,
        )
        self._create_submission(
            eqvas,
            "78",
            self._make_aware(self.order.start_date + timedelta(days=1)),
        )

        self.client.force_login(self.doctor_user)
        response = self.client.get(
            self.doctor_url,
            {"patient_id": self.patient.id, "package_id": self.order.id},
        )

        self.assertNotContains(response, "EQ-VAS评分：78.00")

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
        self.assertContains(response, "异常：")

    def test_mobile_health_records_shows_new_general_monitoring_card(self):
        measured_at = self._make_aware(self.order.start_date, hour=10)
        HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BLOOD_KETONE,
            source=MetricSource.MANUAL,
            value_main=Decimal("0.50"),
            measured_at=measured_at,
        )

        self.client.force_login(self.doctor_user)
        response = self.client.get(
            self.doctor_url,
            {"patient_id": self.patient.id, "package_id": self.order.id},
        )

        types = [item["type"] for item in response.context["health_stats"]]
        self.assertIn("ketone", types)

    def test_health_records_hide_unconfigured_items_and_omit_zero_abnormal(self):
        measured_at = self._make_aware(self.order.start_date, hour=9)
        HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BODY_TEMPERATURE,
            source=MetricSource.MANUAL,
            value_main=Decimal("36.80"),
            measured_at=measured_at,
        )

        self.client.force_login(self.doctor_user)
        doctor_response = self.client.get(f"{self.doctor_url}?patient_id={self.patient.id}")
        self.assertEqual(doctor_response.status_code, 200)

        self.client.force_login(self.patient_user)
        patient_response = self.client.get(self.patient_url)
        self.assertEqual(patient_response.status_code, 200)

        for response in (doctor_response, patient_response):
            self.assertEqual(
                [item["type"] for item in response.context["health_stats"]],
                ["temperature"],
            )
            temp_stat = response.context["health_stats"][0]
            self.assertEqual(temp_stat["count"], 1)
            self.assertEqual(temp_stat["abnormal"], 0)
            self.assertEqual(response.context["health_survey_stats"], [])
            self.assertEqual(response.context["checkup_stats"], [])
            self.assertContains(response, "体温")
            self.assertContains(response, "记录：1次")
            self.assertNotContains(response, "异常：0次")
            self.assertNotContains(response, "血压")
            self.assertNotContains(response, "抑郁评估")

    def test_mobile_health_records_shows_questionnaire_submission_count(self):
        questionnaire, _ = Questionnaire.objects.get_or_create(
            code=QuestionnaireCode.Q_COUGH,
            defaults={"name": "咳嗽与痰色评估", "is_active": True},
        )
        self._create_submission(
            questionnaire,
            "6",
            self._make_aware(self.order.start_date, hour=12),
        )

        self.client.force_login(self.doctor_user)
        response = self.client.get(f"{self.doctor_url}?patient_id={self.patient.id}")

        self.assertEqual(response.status_code, 200)
        cough_stat = next(
            item
            for item in response.context["health_survey_stats"]
            if item["questionnaire_id"] == questionnaire.id
        )
        self.assertEqual(cough_stat["count"], 1)
        self.assertEqual(cough_stat["abnormal"], 0)
        self.assertNotContains(response, "异常：")

    def test_mobile_health_records_shows_oral_mucosa_questionnaire_submission(self):
        questionnaire, _ = Questionnaire.objects.get_or_create(
            code=QuestionnaireCode.Q_KQNMLB,
            defaults={"name": "口腔黏膜损伤自评量表", "is_active": True},
        )
        self._create_submission(
            questionnaire,
            "4",
            self._make_aware(self.order.start_date, hour=16),
        )

        self.client.force_login(self.doctor_user)
        response = self.client.get(f"{self.doctor_url}?patient_id={self.patient.id}")

        self.assertEqual(response.status_code, 200)
        oral_stat = next(
            item
            for item in response.context["health_survey_stats"]
            if item["questionnaire_id"] == questionnaire.id
        )
        self.assertEqual(oral_stat["count"], 1)
        self.assertEqual(oral_stat["abnormal"], 0)
        self.assertContains(response, "口腔黏膜损伤自评量表")

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
        questionnaire, _ = Questionnaire.objects.get_or_create(
            code=QuestionnaireCode.Q_COUGH,
            defaults={"name": "咳嗽与痰色评估", "is_active": True},
        )
        self._create_submission(
            questionnaire,
            "5",
            self._make_aware(self.order.start_date, hour=14),
        )
        self._create_metric_alert(
            MetricType.BODY_TEMPERATURE,
            self._make_aware(self.order.start_date, hour=10),
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
            item["questionnaire_id"]: (item["count"], item["abnormal"])
            for item in doctor_response.context["health_survey_stats"]
        }
        patient_survey = {
            item["questionnaire_id"]: (item["count"], item["abnormal"])
            for item in patient_response.context["health_survey_stats"]
        }
        self.assertEqual(doctor_survey, patient_survey)
