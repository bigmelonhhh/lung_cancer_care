from datetime import datetime, timedelta
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from core.models import CheckupLibrary, DailyTask
from core.models.choices import PlanItemCategory, TaskStatus
from health_data.models import HealthMetric, MetricType
from users.models import CustomUser, PatientProfile


class HealthRecordDetailReviewRecordTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = CustomUser.objects.create_user(
            username="testpatient_health_record_detail",
            password="password",
            wx_openid="test_openid_health_record_detail",
        )
        self.patient = PatientProfile.objects.create(user=self.user, name="Test Patient")
        self.client.force_login(self.user)
        self.url = reverse("web_patient:health_record_detail")

    def test_review_record_filters_by_checkup_id_and_month(self):
        ct = CheckupLibrary.objects.create(name="胸部CT", code="CT_CHEST", is_active=True)
        blood = CheckupLibrary.objects.create(name="血常规", code="BLOOD_ROUTINE", is_active=True)

        today = timezone.localdate()
        month = today.strftime("%Y-%m")

        DailyTask.objects.create(
            patient=self.patient,
            task_date=today,
            task_type=PlanItemCategory.CHECKUP,
            title="胸部CT",
            status=TaskStatus.COMPLETED,
            completed_at=timezone.now(),
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
            task_date=today,
            task_type=PlanItemCategory.CHECKUP,
            title="血常规",
            status=TaskStatus.COMPLETED,
            interaction_payload={"checkup_id": blood.id},
        )

        response = self.client.get(
            self.url,
            {
                "type": "review_record",
                "title": "胸部CT",
                "checkup_id": ct.id,
                "month": month,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["record_type"], "review_record")
        self.assertEqual(response.context["title"], "胸部CT")
        self.assertEqual(len(response.context["records"]), 2)

        ids = {r["id"] for r in response.context["records"]}
        self.assertEqual(ids, set(DailyTask.objects.filter(patient=self.patient, interaction_payload__checkup_id=ct.id).values_list("id", flat=True)))

        ajax_resp = self.client.get(
            self.url,
            {
                "type": "review_record",
                "title": "胸部CT",
                "checkup_id": ct.id,
                "month": month,
                "page": 1,
                "limit": 1,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(ajax_resp.status_code, 200)
        payload = ajax_resp.json()
        self.assertIn("records", payload)
        self.assertEqual(len(payload["records"]), 1)

    def test_medical_detail_renders_check_icon_and_hides_value(self):
        tz = timezone.get_current_timezone()
        now = timezone.localtime(timezone.now())
        month = now.strftime("%Y-%m")

        HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.USE_MEDICATED,
            measured_at=timezone.make_aware(
                datetime(now.year, now.month, 2, 10, 0), tz
            ),
            value_main=Decimal("123.45"),
        )

        response = self.client.get(
            self.url,
            {"type": "medical", "title": "用药", "month": month},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-testid="medicated-check"')
        self.assertNotContains(response, "123.45")

        ajax_resp = self.client.get(
            self.url,
            {"type": "medical", "title": "用药", "month": month, "page": 1},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(ajax_resp.status_code, 200)
        payload = ajax_resp.json()
        self.assertEqual(payload["records"][0]["data"][0]["key"], "medicated")
        self.assertEqual(payload["records"][0]["data"][0]["value"], "")
