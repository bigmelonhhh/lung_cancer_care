from datetime import datetime
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from core.models import CheckupLibrary, DailyTask
from core.models.choices import PlanItemCategory, TaskStatus
from health_data.models import HealthMetric, MetricType
from market.models import Product, Order
from users.models import CustomUser, PatientProfile


class HealthRecordDetailVisibilityTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = CustomUser.objects.create_user(
            username="testpatient_health_record_detail_visibility",
            password="password",
            wx_openid="test_openid_health_record_detail_visibility",
        )
        self.patient = PatientProfile.objects.create(user=self.user, name="Test Patient")
        product = Product.objects.create(
            name="VIP 服务包", price=Decimal("199.00"), duration_days=30
        )
        Order.objects.create(
            patient=self.patient,
            product=product,
            amount=Decimal("199.00"),
            status=Order.Status.PAID,
            paid_at=timezone.now(),
        )
        self.client.force_login(self.user)
        self.url = reverse("web_patient:health_record_detail")

    def test_temperature_from_health_records_shows_operation_controls(self):
        month = timezone.localtime(timezone.now()).strftime("%Y-%m")
        metric = HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BODY_TEMPERATURE,
            source="manual",
            measured_at=timezone.now(),
            value_main=Decimal("36.50"),
        )

        response = self.client.get(
            self.url,
            {
                "type": "temperature",
                "title": "体温",
                "month": month,
                "source": "health_records",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["show_operation_controls"])
        self.assertTrue(response.context["show_add_button"])
        self.assertContains(response, "新增数据")
        self.assertContains(response, f"handleDelete('{metric.id}')")
        self.assertContains(response, f"openEditModal('{metric.id}')")
        self.assertContains(response, "手动填写")

    def test_temperature_from_survey_list_hides_operation_controls_and_add(self):
        month = timezone.localtime(timezone.now()).strftime("%Y-%m")
        metric = HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BODY_TEMPERATURE,
            source="manual",
            measured_at=timezone.now(),
            value_main=Decimal("36.50"),
        )

        response = self.client.get(
            self.url,
            {
                "type": "temperature",
                "title": "体温",
                "month": month,
                "source": "survey_list",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["show_operation_controls"])
        self.assertFalse(response.context["show_add_button"])
        self.assertNotContains(response, "新增数据")
        self.assertNotContains(response, f"handleDelete('{metric.id}')")
        self.assertNotContains(response, f"openEditModal('{metric.id}')")
        self.assertNotContains(response, "手动填写")
        self.assertNotContains(response, "设备上传")

    def test_review_record_from_checkup_list_hides_operation_controls_and_add(self):
        today = timezone.localdate()
        month = today.strftime("%Y-%m")

        ct = CheckupLibrary.objects.create(name="胸部CT", code="CT_CHEST", is_active=True)
        task = DailyTask.objects.create(
            patient=self.patient,
            task_date=today,
            task_type=PlanItemCategory.CHECKUP,
            title="胸部CT",
            status=TaskStatus.COMPLETED,
            completed_at=timezone.make_aware(
                datetime(today.year, today.month, today.day, 10, 0),
                timezone.get_current_timezone(),
            ),
            interaction_payload={"checkup_id": ct.id},
        )

        response = self.client.get(
            self.url,
            {
                "type": "review_record",
                "title": "胸部CT",
                "checkup_id": ct.id,
                "month": month,
                "source": "checkup_list",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["show_operation_controls"])
        self.assertFalse(response.context["show_add_button"])
        self.assertNotContains(response, "新增数据")
        self.assertNotContains(response, f"handleDelete('{task.id}')")
        self.assertNotContains(response, f"openEditModal('{task.id}')")
