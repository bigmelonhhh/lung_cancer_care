from datetime import timedelta
from decimal import Decimal
from urllib.parse import unquote

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import DailyTask, PlanItem, Questionnaire, TreatmentCycle
from core.models import choices as core_choices
from market.models import Order, Product
from users import choices
from users.models import CustomUser, PatientProfile


@override_settings(DEBUG=True, TEST_PATIENT_ID="1")
class MembershipAccessTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username="member_access_user",
            password="password",
            user_type=choices.UserType.PATIENT,
            wx_openid="test_openid_member_access",
        )
        self.patient = PatientProfile.objects.create(
            user=self.user,
            name="会员测试患者",
            phone="13800000000",
        )
        self.client.force_login(self.user)
        cache.clear()

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def _create_paid_membership_order(self, paid_at=None):
        product = Product.objects.create(
            name="VIP 服务包",
            price=Decimal("199.00"),
            duration_days=30,
            is_active=True,
        )
        return Order.objects.create(
            patient=self.patient,
            product=product,
            amount=Decimal("199.00"),
            status=Order.Status.PAID,
            paid_at=paid_at or timezone.now(),
        )

    def _assert_redirect_contains_buy_path(self, response):
        self.assertEqual(response.status_code, 302)
        buy_path = reverse("market:product_buy")
        decoded_location = unquote(response["Location"])
        self.assertIn(buy_path, decoded_location)

    def _create_active_cycle(self, *, start_date=None, end_date=None):
        today = timezone.localdate()
        return TreatmentCycle.objects.create(
            patient=self.patient,
            name="免费体验疗程",
            start_date=start_date or today,
            end_date=end_date or today,
            cycle_days=((end_date or today) - (start_date or today)).days + 1,
            status=core_choices.TreatmentCycleStatus.IN_PROGRESS,
        )

    def _create_trial_tasks(self, cycle):
        today = timezone.localdate()
        questionnaire = Questionnaire.objects.create(
            name="体验随访问卷",
            code="Q_HOME_TRIAL",
            is_active=True,
        )
        questionnaire_plan = PlanItem.objects.create(
            cycle=cycle,
            category=core_choices.PlanItemCategory.QUESTIONNAIRE,
            template_id=questionnaire.id,
            item_name=questionnaire.name,
            schedule_days=[1],
            status=core_choices.PlanItemStatus.ACTIVE,
        )
        task_specs = (
            (core_choices.PlanItemCategory.MEDICATION, "用药提醒", None),
            (core_choices.PlanItemCategory.MONITORING, "体温监测", None),
            (core_choices.PlanItemCategory.CHECKUP, "复查提醒", None),
            (
                core_choices.PlanItemCategory.QUESTIONNAIRE,
                "随访问卷",
                questionnaire_plan,
            ),
        )
        for task_type, title, plan_item in task_specs:
            DailyTask.objects.create(
                patient=self.patient,
                plan_item=plan_item,
                task_date=today,
                task_type=task_type,
                title=title,
                status=core_choices.TaskStatus.PENDING,
            )

    def test_patient_home_non_member_short_circuit(self):
        response = self.client.get(reverse("web_patient:patient_home"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["is_member"])
        self.assertEqual(response.context["home_plan_access_mode"], "locked")
        self.assertEqual(response.context["service_days"], "0")
        self.assertEqual(response.context["daily_plans"], [])
        self.assertIn(reverse("web_patient:my_medication"), response.content.decode())
        self.assertContains(response, "开通会员解锁今日计划")

    def test_patient_home_member_flag_true(self):
        self._create_paid_membership_order()
        response = self.client.get(reverse("web_patient:patient_home"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["is_member"])
        self.assertEqual(response.context["home_plan_access_mode"], "member")
        self.assertTrue(response.context["can_view_steps"])
        self.assertTrue(response.context["can_view_history"])

    def test_patient_home_trial_shows_all_tasks_without_member_extras(self):
        cycle = self._create_active_cycle()
        self._create_trial_tasks(cycle)

        response = self.client.get(reverse("web_patient:patient_home"))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["is_member"])
        self.assertEqual(response.context["home_plan_access_mode"], "trial")
        self.assertTrue(response.context["can_view_daily_plan"])
        self.assertFalse(response.context["can_view_steps"])
        self.assertFalse(response.context["can_view_history"])
        self.assertEqual(
            {plan["type"] for plan in response.context["daily_plans"]},
            {"medication", "temperature", "checkup", "followup"},
        )
        self.assertContains(response, "用药提醒")
        self.assertContains(response, "体温监测")
        self.assertContains(response, "复查提醒")
        self.assertContains(response, "问卷提醒")
        self.assertNotContains(response, "今日步数")
        self.assertNotContains(response, "查看历史")
        self.assertNotContains(response, "查看我的康复计划")
        self.assertNotContains(response, "开通会员解锁今日计划")
        self.assertTrue(response.context["patient_home_config"]["canUseDailyPlan"])

    def test_non_member_cannot_access_management_plan(self):
        response = self.client.get(reverse("web_patient:management_plan"))
        self._assert_redirect_contains_buy_path(response)

    def test_non_member_can_access_my_medication(self):
        response = self.client.get(reverse("web_patient:my_medication"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "我的用药")

    def test_query_last_metric_non_member_returns_empty(self):
        response = self.client.get(reverse("web_patient:query_last_metric"))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["plans"], {})

    def test_query_last_metric_trial_allows_today_but_not_history(self):
        today = timezone.localdate()
        yesterday = today - timedelta(days=1)
        cycle = self._create_active_cycle(start_date=yesterday, end_date=today)
        for task_date in (yesterday, today):
            DailyTask.objects.create(
                patient=self.patient,
                task_date=task_date,
                task_type=core_choices.PlanItemCategory.MONITORING,
                title="体温监测",
                status=core_choices.TaskStatus.PENDING,
            )

        today_response = self.client.get(reverse("web_patient:query_last_metric"))
        history_response = self.client.get(
            reverse("web_patient:query_last_metric"),
            {"date": yesterday.strftime("%Y-%m-%d")},
        )

        self.assertIn("temperature", today_response.json()["plans"])
        self.assertEqual(history_response.json()["plans"], {})
