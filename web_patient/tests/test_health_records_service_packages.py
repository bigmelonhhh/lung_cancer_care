from datetime import datetime, timedelta
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from core.models import CheckupLibrary, DailyTask
from core.models.choices import PlanItemCategory, TaskStatus
from health_data.models import HealthMetric, MetricType
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

    def test_checkup_library_and_task_counts(self):
        now = timezone.now()
        latest_order = self._create_paid_order(
            paid_at=now - timedelta(days=10), name="新服务包", duration_days=30
        )

        ct = CheckupLibrary.objects.create(name="胸部CT", code="CT_CHEST", is_active=True)
        blood = CheckupLibrary.objects.create(name="血常规", code="BLOOD_ROUTINE", is_active=True)
        CheckupLibrary.objects.create(name="停用项目", code="INACTIVE", is_active=False)

        today = timezone.localdate()
        DailyTask.objects.create(
            patient=self.patient,
            task_date=today - timedelta(days=2),
            task_type=PlanItemCategory.CHECKUP,
            title="胸部CT",
            status=TaskStatus.COMPLETED,
            interaction_payload={"checkup_id": ct.id},
        )
        DailyTask.objects.create(
            patient=self.patient,
            task_date=today - timedelta(days=1),
            task_type=PlanItemCategory.CHECKUP,
            title="胸部CT",
            status=TaskStatus.PENDING,
            interaction_payload={"checkup_id": ct.id},
        )
        DailyTask.objects.create(
            patient=self.patient,
            task_date=today + timedelta(days=1),
            task_type=PlanItemCategory.CHECKUP,
            title="胸部CT",
            status=TaskStatus.PENDING,
            interaction_payload={"checkup_id": ct.id},
        )
        DailyTask.objects.create(
            patient=self.patient,
            task_date=today - timedelta(days=2),
            task_type=PlanItemCategory.CHECKUP,
            title="血常规",
            status=TaskStatus.COMPLETED,
            interaction_payload={"checkup_id": blood.id},
        )

        response = self.client.get(self.url, {"package_id": str(latest_order.id)})
        self.assertEqual(response.status_code, 200)

        stats = {item["lib_id"]: item for item in response.context["checkup_stats"]}
        self.assertIn(ct.id, stats)
        self.assertIn(blood.id, stats)

        self.assertEqual(stats[ct.id]["count"], 1)
        self.assertEqual(stats[ct.id]["abnormal"], 1)
        self.assertEqual(stats[blood.id]["count"], 1)
        self.assertEqual(stats[blood.id]["abnormal"], 0)
