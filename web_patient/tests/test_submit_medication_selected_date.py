from datetime import timedelta

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import DailyTask, choices as core_choices
from health_data.models import HealthMetric, MetricType
from users.models import CustomUser, PatientProfile


class SubmitMedicationSelectedDateTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = CustomUser.objects.create_user(
            username="test_submit_medication_selected_date",
            password="password",
            wx_openid="test_openid_submit_medication_selected_date",
        )
        self.patient = PatientProfile.objects.create(user=self.user, name="Test Patient")
        self.client.force_login(self.user)

    def test_submit_medication_uses_selected_date_and_updates_task(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        DailyTask.objects.create(
            patient=self.patient,
            task_date=yesterday,
            task_type=core_choices.PlanItemCategory.MEDICATION,
            title="用药提醒",
            status=core_choices.TaskStatus.TERMINATED,
        )

        url = reverse("web_patient:submit_medication")
        resp = self.client.post(url, {"selected_date": yesterday.strftime("%Y-%m-%d")})
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertTrue(payload["success"])

        task = DailyTask.objects.get(
            patient=self.patient,
            task_date=yesterday,
            task_type=core_choices.PlanItemCategory.MEDICATION,
        )
        self.assertEqual(task.status, core_choices.TaskStatus.COMPLETED)

        metric = (
            HealthMetric.objects.filter(
                patient=self.patient,
                metric_type=MetricType.USE_MEDICATED,
            )
            .order_by("-measured_at")
            .first()
        )
        self.assertIsNotNone(metric)
        self.assertEqual(timezone.localtime(metric.measured_at).date(), yesterday)

    def test_submit_medication_default_date_is_today(self):
        today = timezone.localdate()
        DailyTask.objects.create(
            patient=self.patient,
            task_date=today,
            task_type=core_choices.PlanItemCategory.MEDICATION,
            title="用药提醒",
            status=core_choices.TaskStatus.PENDING,
        )

        url = reverse("web_patient:submit_medication")
        resp = self.client.post(url, {})
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertTrue(payload["success"])

        task = DailyTask.objects.get(
            patient=self.patient,
            task_date=today,
            task_type=core_choices.PlanItemCategory.MEDICATION,
        )
        self.assertEqual(task.status, core_choices.TaskStatus.COMPLETED)

