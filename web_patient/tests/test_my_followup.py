from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import DailyTask, PlanItem, TreatmentCycle, choices as core_choices
from core.models.questionnaire import Questionnaire
from market.models import Product, Order
from users import choices as user_choices
from users.models import CustomUser, PatientProfile


class MyFollowupTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username="testpatient_my_followup",
            password="password",
            user_type=user_choices.UserType.PATIENT,
            wx_openid="test_openid_my_followup",
        )
        self.patient = PatientProfile.objects.create(user=self.user, name="Test Patient")
        product = Product.objects.create(
            name="VIP 服务包", price=Decimal("199.00"), duration_days=30, is_active=True
        )
        Order.objects.create(
            patient=self.patient,
            product=product,
            amount=Decimal("199.00"),
            status=Order.Status.PAID,
            paid_at=timezone.now(),
        )
        self.client.force_login(self.user)

        self.url = reverse("web_patient:my_followup")

    def test_my_followup_renders_cycles_and_tasks(self):
        today = timezone.localdate()

        q1 = Questionnaire.objects.create(name="体能评估", code="Q_TEST_PHYSICAL")

        cycle_current = TreatmentCycle.objects.create(
            patient=self.patient,
            name="第三疗程",
            start_date=today - timedelta(days=10),
            end_date=today + timedelta(days=10),
            cycle_days=21,
            status=core_choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        cycle_past = TreatmentCycle.objects.create(
            patient=self.patient,
            name="第二疗程",
            start_date=today - timedelta(days=40),
            end_date=today - timedelta(days=20),
            cycle_days=21,
            status=core_choices.TreatmentCycleStatus.COMPLETED,
        )

        plan1 = PlanItem.objects.create(
            cycle=cycle_current,
            category=core_choices.PlanItemCategory.QUESTIONNAIRE,
            template_id=q1.id,
            item_name="问卷提醒",
            schedule_days=[1],
            status=core_choices.PlanItemStatus.ACTIVE,
        )

        DailyTask.objects.create(
            patient=self.patient,
            plan_item=plan1,
            task_date=today,
            task_type=core_choices.PlanItemCategory.QUESTIONNAIRE,
            title="问卷提醒",
            status=core_choices.TaskStatus.PENDING,
        )

        past_plan = PlanItem.objects.create(
            cycle=cycle_past,
            category=core_choices.PlanItemCategory.QUESTIONNAIRE,
            template_id=q1.id,
            item_name="问卷提醒",
            schedule_days=[1],
            status=core_choices.PlanItemStatus.ACTIVE,
        )
        DailyTask.objects.create(
            patient=self.patient,
            plan_item=past_plan,
            task_date=cycle_past.end_date,
            task_type=core_choices.PlanItemCategory.QUESTIONNAIRE,
            title="问卷提醒",
            status=core_choices.TaskStatus.TERMINATED,
        )

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

        cycles = response.context["cycles"]
        self.assertEqual(len(cycles), 2)
        self.assertIn("当前疗程", cycles[0]["name"])

        current_tasks = cycles[0]["tasks"]
        self.assertEqual(len(current_tasks), 1)
        self.assertEqual(current_tasks[0]["date"], today.strftime("%Y-%m-%d"))
        self.assertEqual(current_tasks[0]["status"], "incomplete")
        self.assertEqual(current_tasks[0]["status_text"], "未完成")

        past_tasks = cycles[1]["tasks"]
        self.assertEqual(len(past_tasks), 1)
        self.assertEqual(past_tasks[0]["status"], "terminated")
