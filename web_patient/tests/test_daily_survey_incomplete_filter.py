from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import DailyTask, PlanItem, TreatmentCycle, Questionnaire
from core.models import choices as core_choices
from market.models import Product, Order
from users import choices as user_choices
from users.models import CustomUser, PatientProfile


class DailySurveyIncompleteFilterTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username="testpatient_daily_survey_filter",
            password="password",
            user_type=user_choices.UserType.PATIENT,
            wx_openid="test_openid_daily_survey_filter",
        )
        self.patient = PatientProfile.objects.create(
            user=self.user,
            name="Test Patient",
            phone="13900000001",
        )
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

        self.today = timezone.localdate()
        self.cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="第一疗程",
            start_date=self.today - timedelta(days=3),
            end_date=self.today + timedelta(days=3),
            cycle_days=7,
            status=core_choices.TreatmentCycleStatus.IN_PROGRESS,
        )

        self.q5 = Questionnaire.objects.create(name="问卷5", code="Q_TEST_5", is_active=True)
        self.q6 = Questionnaire.objects.create(name="问卷6", code="Q_TEST_6", is_active=True)
        self.q7 = Questionnaire.objects.create(name="问卷7", code="Q_TEST_7", is_active=True)

        self.plan5 = PlanItem.objects.create(
            cycle=self.cycle,
            category=core_choices.PlanItemCategory.QUESTIONNAIRE,
            template_id=self.q5.id,
            item_name="问卷提醒",
            schedule_days=[1],
            status=core_choices.PlanItemStatus.ACTIVE,
        )
        self.plan6 = PlanItem.objects.create(
            cycle=self.cycle,
            category=core_choices.PlanItemCategory.QUESTIONNAIRE,
            template_id=self.q6.id,
            item_name="问卷提醒",
            schedule_days=[1],
            status=core_choices.PlanItemStatus.ACTIVE,
        )
        self.plan7 = PlanItem.objects.create(
            cycle=self.cycle,
            category=core_choices.PlanItemCategory.QUESTIONNAIRE,
            template_id=self.q7.id,
            item_name="问卷提醒",
            schedule_days=[1],
            status=core_choices.PlanItemStatus.ACTIVE,
        )

    def test_daily_survey_filters_completed_when_ids_mixed(self):
        DailyTask.objects.create(
            patient=self.patient,
            plan_item=self.plan6,
            task_date=self.today,
            task_type=core_choices.PlanItemCategory.QUESTIONNAIRE,
            title="问卷提醒",
            status=core_choices.TaskStatus.PENDING,
        )
        DailyTask.objects.create(
            patient=self.patient,
            plan_item=self.plan7,
            task_date=self.today,
            task_type=core_choices.PlanItemCategory.QUESTIONNAIRE,
            title="问卷提醒",
            status=core_choices.TaskStatus.COMPLETED,
        )
        DailyTask.objects.create(
            patient=self.patient,
            plan_item=self.plan5,
            task_date=self.today,
            task_type=core_choices.PlanItemCategory.QUESTIONNAIRE,
            title="问卷提醒",
            status=core_choices.TaskStatus.COMPLETED,
        )

        url = reverse("web_patient:daily_survey") + f"?ids={self.q6.id},{self.q7.id},{self.q5.id}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        survey_ids = response.context["survey_ids"]
        self.assertIn(str(self.q6.id), survey_ids)
        self.assertNotIn(str(self.q5.id), survey_ids)
        self.assertNotIn(str(self.q7.id), survey_ids)

    def test_daily_survey_empty_when_all_completed(self):
        DailyTask.objects.create(
            patient=self.patient,
            plan_item=self.plan6,
            task_date=self.today,
            task_type=core_choices.PlanItemCategory.QUESTIONNAIRE,
            title="问卷提醒",
            status=core_choices.TaskStatus.COMPLETED,
        )
        DailyTask.objects.create(
            patient=self.patient,
            plan_item=self.plan7,
            task_date=self.today,
            task_type=core_choices.PlanItemCategory.QUESTIONNAIRE,
            title="问卷提醒",
            status=core_choices.TaskStatus.COMPLETED,
        )

        url = reverse("web_patient:daily_survey") + f"?ids={self.q6.id},{self.q7.id}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["survey_ids"], "[]")
        self.assertIn("暂无需要填写的随访问卷", response.context["error"])

    def test_home_followup_url_contains_only_pending_ids(self):
        DailyTask.objects.create(
            patient=self.patient,
            plan_item=self.plan6,
            task_date=self.today,
            task_type=core_choices.PlanItemCategory.QUESTIONNAIRE,
            title="问卷提醒",
            status=core_choices.TaskStatus.PENDING,
        )
        DailyTask.objects.create(
            patient=self.patient,
            plan_item=self.plan7,
            task_date=self.today,
            task_type=core_choices.PlanItemCategory.QUESTIONNAIRE,
            title="问卷提醒",
            status=core_choices.TaskStatus.COMPLETED,
        )

        response = self.client.get(reverse("web_patient:patient_home"))
        self.assertEqual(response.status_code, 200)
        daily_plans = response.context.get("daily_plans") or []
        followup_plan = next((p for p in daily_plans if p.get("type") == "followup"), None)
        self.assertIsNotNone(followup_plan)
        url = followup_plan.get("url") or ""
        self.assertIn(f"ids={self.q6.id}", url)
        self.assertNotIn(str(self.q7.id), url)
