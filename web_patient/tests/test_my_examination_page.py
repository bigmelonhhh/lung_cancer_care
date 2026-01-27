from django.test import Client, TestCase
from django.urls import reverse

from market.models import Product, Order
from users.models import CustomUser, PatientProfile
from decimal import Decimal
from django.utils import timezone
from datetime import timedelta

from core.models import DailyTask, TreatmentCycle
from core.models.choices import PlanItemCategory, TaskStatus


class MyExaminationPageTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = CustomUser.objects.create_user(
            username="testpatient_my_examination",
            password="password",
            wx_openid="test_openid_my_examination",
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

    def test_my_examination_renders_cycles_and_checkup_link(self):
        today = timezone.localdate()
        cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="第三疗程",
            start_date=today - timedelta(days=7),
            end_date=today + timedelta(days=7),
            cycle_days=14,
        )
        DailyTask.objects.create(
            patient=self.patient,
            task_date=today,
            task_type=PlanItemCategory.CHECKUP,
            title="复查提醒",
            status=TaskStatus.PENDING,
        )

        resp = self.client.get(reverse("web_patient:my_examination"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "我的复查")
        self.assertContains(resp, cycle.name)
        self.assertContains(resp, "复查")

