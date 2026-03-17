from pathlib import Path
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import DailyTask, PlanItem, Questionnaire, TreatmentCycle
from core.models import choices as core_choices
from market.models import Order, Product
from users import choices as user_choices
from users.models import CustomUser, PatientProfile


class FollowupPlanCompletionTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username="testpatient_followup_refresh_fix",
            password="password",
            user_type=user_choices.UserType.PATIENT,
            wx_openid="test_openid_followup_refresh_fix",
        )
        self.patient = PatientProfile.objects.create(
            user=self.user,
            name="Test Patient",
            phone="13900000011",
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
        self.questionnaire = Questionnaire.objects.create(
            name="问卷A", code="Q_REFRESH_FIX_A", is_active=True
        )
        self.plan_item = PlanItem.objects.create(
            cycle=self.cycle,
            category=core_choices.PlanItemCategory.QUESTIONNAIRE,
            template_id=self.questionnaire.id,
            item_name="问卷提醒",
            schedule_days=[1],
            status=core_choices.PlanItemStatus.ACTIVE,
        )

    def test_patient_home_followup_completed_when_no_pending_questionnaire_ids(self):
        DailyTask.objects.create(
            patient=self.patient,
            plan_item=self.plan_item,
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
        self.assertEqual(followup_plan.get("status"), "completed")
        self.assertEqual(followup_plan.get("subtitle"), "已完成随访任务")
        self.assertEqual(followup_plan.get("url"), "")

    @patch("web_patient.views.record.HealthMetricService.query_last_metric_for_date")
    @patch("web_patient.views.record.get_daily_plan_summary")
    def test_query_last_metric_followup_no_pending_ids_forced_completed(
        self, mock_summary, mock_metric
    ):
        mock_summary.return_value = [
            {
                "title": "问卷提醒",
                "status": core_choices.TaskStatus.PENDING,
                "subtitle": "请及时完成您的随访任务",
                "questionnaire_ids": [],
            }
        ]
        mock_metric.return_value = {}

        response = self.client.get(
            reverse("web_patient:query_last_metric"),
            {"date": self.today.strftime("%Y-%m-%d")},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["plans"]["followup"]["status"], "completed")
        self.assertEqual(data["plans"]["followup"]["subtitle"], "已完成随访任务")


class FollowupRefreshTemplateTests(SimpleTestCase):
    def test_patient_home_uses_single_pageshow_refresh_entry(self):
        template_path = Path(settings.BASE_DIR) / "templates" / "web_patient" / "patient_home.html"
        content = template_path.read_text(encoding="utf-8")
        script_path = Path(settings.BASE_DIR) / "static" / "web_patient" / "patient_home.js"
        script_content = script_path.read_text(encoding="utf-8")

        self.assertIn("patient_home.js", content)
        self.assertEqual(
            script_content.count("window.addEventListener('pageshow', handleHomePageShow);"),
            1,
        )
        self.assertNotIn("window.addEventListener('popstate', consumeHomeRefreshFlag);", script_content)
        self.assertNotIn("document.addEventListener('visibilitychange'", script_content)
        self.assertIn("async function consumeRefreshMarkersAndSync()", script_content)
        self.assertIn("if (options && options.followupSubmitted && !hasFollowupPlan)", script_content)
        self.assertIn("markFollowupCompletedFallback();", script_content)

    def test_daily_survey_preserves_history_back_and_followup_refresh_flag(self):
        template_path = (
            Path(settings.BASE_DIR)
            / "templates"
            / "web_patient"
            / "followup"
            / "daily_survey.html"
        )
        content = template_path.read_text(encoding="utf-8")

        self.assertIn("localStorage.setItem('refresh_flag', 'true');", content)
        self.assertIn('"followup_completed": true', content)
        self.assertIn("history.back();", content)
