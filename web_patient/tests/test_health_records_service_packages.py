from datetime import datetime, timedelta
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from core.models import CheckupLibrary, Questionnaire
from health_data.models import (
    HealthMetric,
    MetricType,
    QuestionnaireSubmission,
    ReportImage,
    UploadSource,
)
from health_data.services.report_service import ReportUploadService
from market.models import Product, Order
from users.models import CustomUser, PatientProfile


class HealthRecordsServicePackageTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = CustomUser.objects.create_user(
            username="testpatient_health_records",
            password="password",
            wx_openid="test_openid_health_records",
        )
        self.patient = PatientProfile.objects.create(user=self.user, name="Test Patient")
        self.client.force_login(self.user)

        self.url = reverse("web_patient:health_records")

    def _create_paid_order(self, *, paid_at, name, duration_days):
        product = Product.objects.create(
            name=name, price=Decimal("199.00"), duration_days=duration_days
        )
        return Order.objects.create(
            patient=self.patient,
            product=product,
            amount=Decimal("199.00"),
            status=Order.Status.PAID,
            paid_at=paid_at,
        )

    def test_default_select_latest_service_package_and_date_range_filters_metrics(self):
        now = timezone.now()
        older_order = self._create_paid_order(
            paid_at=now - timedelta(days=60), name="旧服务包", duration_days=20
        )
        latest_order = self._create_paid_order(
            paid_at=now - timedelta(days=10), name="新服务包", duration_days=30
        )

        tz = timezone.get_current_timezone()
        HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BODY_TEMPERATURE,
            measured_at=timezone.make_aware(
                datetime.combine(older_order.start_date + timedelta(days=1), datetime.min.time()),
                tz,
            ),
            value_main=Decimal("36.5"),
        )
        HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BODY_TEMPERATURE,
            measured_at=timezone.make_aware(
                datetime.combine(latest_order.start_date + timedelta(days=1), datetime.min.time()),
                tz,
            ),
            value_main=Decimal("36.6"),
        )

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

        self.assertIn("service_packages", response.context)
        self.assertEqual(len(response.context["service_packages"]), 2)
        self.assertEqual(response.context["selected_package_id"], latest_order.id)

        selected_range = response.context["selected_date_range"]
        self.assertEqual(selected_range["start_date"], latest_order.start_date)
        self.assertEqual(selected_range["end_date"], latest_order.end_date)

        temp_item = next(
            item for item in response.context["health_stats"] if item["type"] == "temperature"
        )
        self.assertEqual(temp_item["count"], 1)

    def test_switch_service_package_updates_counts_and_date_range(self):
        now = timezone.now()
        older_order = self._create_paid_order(
            paid_at=now - timedelta(days=60), name="旧服务包", duration_days=20
        )
        latest_order = self._create_paid_order(
            paid_at=now - timedelta(days=10), name="新服务包", duration_days=30
        )

        tz = timezone.get_current_timezone()
        HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BODY_TEMPERATURE,
            measured_at=timezone.make_aware(
                datetime.combine(older_order.start_date + timedelta(days=1), datetime.min.time()),
                tz,
            ),
            value_main=Decimal("36.5"),
        )
        HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BODY_TEMPERATURE,
            measured_at=timezone.make_aware(
                datetime.combine(latest_order.start_date + timedelta(days=1), datetime.min.time()),
                tz,
            ),
            value_main=Decimal("36.6"),
        )

        response = self.client.get(self.url, {"package_id": str(older_order.id)})
        self.assertEqual(response.status_code, 200)

        self.assertEqual(response.context["selected_package_id"], older_order.id)
        selected_range = response.context["selected_date_range"]
        self.assertEqual(selected_range["start_date"], older_order.start_date)
        self.assertEqual(selected_range["end_date"], older_order.end_date)

        temp_item = next(
            item for item in response.context["health_stats"] if item["type"] == "temperature"
        )
        self.assertEqual(temp_item["count"], 1)

    def test_survey_cards_only_show_active_questionnaires_submitted_in_selected_package(self):
        now = timezone.now()
        older_order = self._create_paid_order(
            paid_at=now - timedelta(days=70), name="旧服务包", duration_days=20
        )
        current_order = self._create_paid_order(
            paid_at=now - timedelta(days=10), name="当前服务包", duration_days=30
        )
        active = Questionnaire.objects.create(
            name="术后生活质量问卷",
            code="Q_DYNAMIC_ARCHIVE",
            is_active=True,
            sort_order=1,
        )
        no_data = Questionnaire.objects.create(
            name="启用但无记录问卷",
            code="Q_DYNAMIC_EMPTY",
            is_active=True,
            sort_order=2,
        )
        inactive = Questionnaire.objects.create(
            name="停用问卷",
            code="Q_DYNAMIC_OFF",
            is_active=False,
            sort_order=3,
        )
        tz = timezone.get_current_timezone()

        def create_submission(questionnaire, score, submitted_date):
            item = QuestionnaireSubmission.objects.create(
                patient=self.patient,
                questionnaire=questionnaire,
                total_score=Decimal(score),
            )
            submitted_at = timezone.make_aware(
                datetime.combine(submitted_date, datetime.min.time()), tz
            )
            QuestionnaireSubmission.objects.filter(pk=item.pk).update(
                created_at=submitted_at
            )

        create_submission(
            active,
            "6",
            current_order.start_date + timedelta(days=1),
        )
        create_submission(
            active,
            "2",
            older_order.start_date + timedelta(days=1),
        )
        create_submission(
            inactive,
            "3",
            current_order.start_date + timedelta(days=2),
        )

        response = self.client.get(
            self.url,
            {"package_id": str(current_order.id)},
        )

        cards = response.context["health_survey_stats"]
        self.assertEqual([item["questionnaire_id"] for item in cards], [active.id])
        self.assertEqual(cards[0]["title"], active.name)
        self.assertEqual(cards[0]["count"], 1)
        self.assertEqual(cards[0]["latest_score"], Decimal("6.00"))
        self.assertNotContains(response, no_data.name)
        self.assertNotContains(response, inactive.name)
        self.assertContains(response, f"questionnaire_id={active.id}")
        self.assertContains(response, f"package_id={current_order.id}")

    def test_eq5d5l_survey_card_displays_latest_health_utility_index(self):
        order = self._create_paid_order(
            paid_at=timezone.now() - timedelta(days=10),
            name="EQ5D5L服务包",
            duration_days=30,
        )
        eq5d5l = Questionnaire.objects.create(
            name="EQ5D5L量表",
            code="Q_EQ5D5L",
            is_active=True,
            sort_order=1,
        )
        submission = QuestionnaireSubmission.objects.create(
            patient=self.patient,
            questionnaire=eq5d5l,
            total_score=Decimal("0.55"),
        )
        submitted_at = timezone.make_aware(
            datetime.combine(
                order.start_date + timedelta(days=1),
                datetime.min.time(),
            ),
            timezone.get_current_timezone(),
        )
        QuestionnaireSubmission.objects.filter(pk=submission.pk).update(
            created_at=submitted_at
        )

        response = self.client.get(self.url, {"package_id": str(order.id)})

        self.assertContains(response, "健康效用指数：0.55")

    def test_checkup_library_and_task_counts(self):
        now = timezone.now()
        latest_order = self._create_paid_order(
            paid_at=now - timedelta(days=10), name="新服务包", duration_days=30
        )

        ct = CheckupLibrary.objects.create(name="胸部CT", code="CT_CHEST", is_active=True)
        blood = CheckupLibrary.objects.create(name="血常规", code="BLOOD_ROUTINE", is_active=True)
        CheckupLibrary.objects.create(name="停用项目", code="INACTIVE", is_active=False)

        tz = timezone.get_current_timezone()
        HealthMetric.objects.create(
            patient=self.patient,
            metric_type=ct.code,
            measured_at=timezone.make_aware(
                datetime.combine(latest_order.start_date + timedelta(days=1), datetime.min.time()),
                tz,
            ),
            value_main=Decimal("1"),
        )
        HealthMetric.objects.create(
            patient=self.patient,
            metric_type=ct.code,
            measured_at=timezone.make_aware(
                datetime.combine(latest_order.start_date + timedelta(days=2), datetime.min.time()),
                tz,
            ),
            value_main=Decimal("1"),
        )
        HealthMetric.objects.create(
            patient=self.patient,
            metric_type=blood.code,
            measured_at=timezone.make_aware(
                datetime.combine(latest_order.start_date + timedelta(days=1), datetime.min.time()),
                tz,
            ),
            value_main=Decimal("1"),
        )

        ReportUploadService.create_upload(
            self.patient,
            images=[
                {
                    "image_url": "https://example.com/ct-1.png",
                    "record_type": ReportImage.RecordType.CHECKUP,
                    "checkup_item_id": ct.id,
                    "report_date": latest_order.start_date + timedelta(days=1),
                }
            ],
            upload_source=UploadSource.CHECKUP_PLAN,
        )
        ReportUploadService.create_upload(
            self.patient,
            images=[
                {
                    "image_url": "https://example.com/ct-2.png",
                    "record_type": ReportImage.RecordType.CHECKUP,
                    "checkup_item_id": ct.id,
                    "report_date": latest_order.start_date + timedelta(days=2),
                }
            ],
            upload_source=UploadSource.CHECKUP_PLAN,
        )
        ReportUploadService.create_upload(
            self.patient,
            images=[
                {
                    "image_url": "https://example.com/blood-1.png",
                    "record_type": ReportImage.RecordType.CHECKUP,
                    "checkup_item_id": blood.id,
                    "report_date": latest_order.start_date + timedelta(days=1),
                }
            ],
            upload_source=UploadSource.CHECKUP_PLAN,
        )

        response = self.client.get(self.url, {"package_id": str(latest_order.id)})
        self.assertEqual(response.status_code, 200)

        stats = {item["lib_id"]: item for item in response.context["checkup_stats"]}
        self.assertIn(ct.id, stats)
        self.assertIn(blood.id, stats)

        self.assertEqual(stats[ct.id]["code"], ct.code)
        self.assertEqual(stats[blood.id]["code"], blood.code)

        self.assertEqual(stats[ct.id]["count"], 2)
        self.assertEqual(stats[ct.id]["abnormal"], 0)
        self.assertEqual(stats[blood.id]["count"], 1)
        self.assertEqual(stats[blood.id]["abnormal"], 0)
