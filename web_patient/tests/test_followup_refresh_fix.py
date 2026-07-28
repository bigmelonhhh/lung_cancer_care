from pathlib import Path
from datetime import timedelta
from decimal import Decimal
import json
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.conf import settings
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from core.models import DailyTask, PlanItem, Questionnaire, TreatmentCycle
from core.models import choices as core_choices
from market.models import Order, Product
from users import choices as user_choices
from users.models import CustomUser, PatientProfile
from web_patient.views import home as home_views


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

    def test_patient_home_followup_success_param_keeps_backlog_pending(self):
        yesterday = self.today - timedelta(days=1)
        DailyTask.objects.create(
            patient=self.patient,
            plan_item=self.plan_item,
            task_date=yesterday,
            task_type=core_choices.PlanItemCategory.QUESTIONNAIRE,
            title="问卷提醒",
            status=core_choices.TaskStatus.PENDING,
        )
        DailyTask.objects.create(
            patient=self.patient,
            plan_item=self.plan_item,
            task_date=self.today,
            task_type=core_choices.PlanItemCategory.QUESTIONNAIRE,
            title="问卷提醒",
            status=core_choices.TaskStatus.COMPLETED,
        )

        response = self.client.get(reverse("web_patient:patient_home"), {"followup": "true"})
        self.assertEqual(response.status_code, 200)

        daily_plans = response.context.get("daily_plans") or []
        followup_plan = next((p for p in daily_plans if p.get("type") == "followup"), None)
        self.assertIsNotNone(followup_plan)
        self.assertEqual(followup_plan.get("status"), "pending")
        self.assertEqual(followup_plan.get("subtitle"), "请及时完成您的随访任务")
        self.assertIn("source=home", followup_plan.get("url") or "")

    def test_query_last_metric_without_date_matches_home_followup_window(self):
        yesterday = self.today - timedelta(days=1)
        DailyTask.objects.create(
            patient=self.patient,
            plan_item=self.plan_item,
            task_date=yesterday,
            task_type=core_choices.PlanItemCategory.QUESTIONNAIRE,
            title="问卷提醒",
            status=core_choices.TaskStatus.PENDING,
        )
        DailyTask.objects.create(
            patient=self.patient,
            plan_item=self.plan_item,
            task_date=self.today,
            task_type=core_choices.PlanItemCategory.QUESTIONNAIRE,
            title="问卷提醒",
            status=core_choices.TaskStatus.COMPLETED,
        )

        home_response = self.client.get(reverse("web_patient:patient_home"))
        self.assertEqual(home_response.status_code, 200)
        daily_plans = home_response.context.get("daily_plans") or []
        followup_plan = next((p for p in daily_plans if p.get("type") == "followup"), None)
        self.assertIsNotNone(followup_plan)

        response = self.client.get(reverse("web_patient:query_last_metric"))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["plans"]["followup"]["status"], followup_plan.get("status"))
        self.assertEqual(
            data["plans"]["followup"]["subtitle"], followup_plan.get("subtitle")
        )

        explicit_today_response = self.client.get(
            reverse("web_patient:query_last_metric"),
            {"date": self.today.strftime("%Y-%m-%d")},
        )
        self.assertEqual(explicit_today_response.status_code, 200)
        explicit_today_data = explicit_today_response.json()
        self.assertEqual(explicit_today_data["plans"]["followup"]["status"], "completed")
        self.assertEqual(
            explicit_today_data["plans"]["followup"]["subtitle"], "已完成随访任务"
        )

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

    def test_patient_home_and_query_last_metric_are_never_cached(self):
        home_response = self.client.get(reverse("web_patient:patient_home"))
        self.assertEqual(home_response.status_code, 200)
        home_cache_control = home_response.headers.get("Cache-Control", "")
        self.assertIn("no-cache", home_cache_control)
        self.assertIn("no-store", home_cache_control)

        metric_response = self.client.get(reverse("web_patient:query_last_metric"))
        self.assertEqual(metric_response.status_code, 200)
        metric_cache_control = metric_response.headers.get("Cache-Control", "")
        self.assertIn("no-cache", metric_cache_control)
        self.assertIn("no-store", metric_cache_control)

    @patch("web_patient.views.home.get_daily_plan_summary")
    @patch("web_patient.views.home.generate_menu_auth_url")
    def test_patient_home_json_config_and_quoted_task_title_are_script_safe(
        self, mock_menu_auth_url, mock_daily_plan_summary
    ):
        dangerous_value = (
            '/buy/?next="quoted"&label=single\'\\&payload=</script>'
            '<script>window.injected=true</script>'
        )
        dangerous_title = (
            '复查 "特殊" \'标题 </script>'
            '<script>window.taskInjected=true</script>'
        )
        mock_menu_auth_url.return_value = dangerous_value
        mock_daily_plan_summary.return_value = [
            {
                "title": dangerous_title,
                "status": core_choices.TaskStatus.PENDING,
            }
        ]
        cache.clear()

        response = self.client.get(reverse("web_patient:patient_home"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        config_start = '<script id="patient-home-config" type="application/json">'
        config_payload = content.split(config_start, 1)[1].split("</script>", 1)[0]
        config = json.loads(config_payload)

        self.assertEqual(config["buyUrl"], dangerous_value)
        self.assertIn(str(escape(dangerous_title)), content)
        self.assertNotIn("<script>window.injected=true</script>", content)
        self.assertNotIn("<script>window.taskInjected=true</script>", content)
        self.assertNotIn('onclick="handleTaskClick(', content)

    @patch("web_patient.views.followup.invalidate_patient_home_plan_cache")
    @patch("web_patient.views.followup.QuestionnaireSubmissionService.submit_questionnaire")
    def test_submit_surveys_invalidates_home_plan_cache(self, mock_submit, mock_invalidate):
        mock_submit.return_value = SimpleNamespace(id=123)

        response = self.client.post(
            reverse("web_patient:submit_surveys"),
            data=json.dumps(
                {
                    "patient_id": self.patient.id,
                    "questionnaire_id": self.questionnaire.id,
                    "answers": [],
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        mock_invalidate.assert_called_once()
        patient_id, dates = mock_invalidate.call_args.args
        self.assertEqual(patient_id, self.patient.id)
        self.assertIn(timezone.localdate(), dates)


class FollowupRefreshTemplateTests(SimpleTestCase):
    def test_home_task_action_url_preserves_existing_query_and_fragment(self):
        builder = getattr(home_views, "_build_home_task_action_url", None)
        self.assertTrue(callable(builder), "patient home must expose an action URL builder")

        action_url = builder(
            {
                "type": "followup",
                "url": "/p/followup/daily/?ids=3%2C5&label=%E9%97%AE%E5%8D%B7+A#pending",
            },
            {"followup": "/p/followup/daily/"},
            "患者 7",
        )
        parsed = urlsplit(action_url)
        query = parse_qs(parsed.query)

        self.assertEqual(parsed.path, "/p/followup/daily/")
        self.assertEqual(parsed.fragment, "pending")
        self.assertEqual(query["ids"], ["3,5"])
        self.assertEqual(query["label"], ["问卷 A"])
        self.assertEqual(query["patient_id"], ["患者 7"])
        self.assertEqual(query["source"], ["home"])

    def test_home_task_action_url_uses_mapping_and_skips_medication(self):
        builder = getattr(home_views, "_build_home_task_action_url", None)
        self.assertTrue(callable(builder), "patient home must expose an action URL builder")

        action_url = builder(
            {"type": "bp_hr"},
            {"bp_hr": "/p/record/bp/?source=calendar&patient_id=old"},
            42,
        )
        query = parse_qs(urlsplit(action_url).query)

        self.assertEqual(query["patient_id"], ["42"])
        self.assertEqual(query["source"], ["home"])
        self.assertEqual(builder({"type": "medication"}, {}, 42), "")

    def test_patient_home_uses_progressive_task_actions(self):
        template_path = Path(settings.BASE_DIR) / "templates" / "web_patient" / "patient_home.html"
        content = template_path.read_text(encoding="utf-8")
        script_path = Path(settings.BASE_DIR) / "static" / "web_patient" / "patient_home.js"
        script_content = script_path.read_text(encoding="utf-8")

        self.assertIn('json_script:"patient-home-config"', content)
        self.assertIn(
            '<script src="{% static \'web_patient/patient_home.js\' %}" defer></script>',
            content,
        )
        self.assertIn('href="{{ plan.action_url }}"', content)
        self.assertIn('data-home-task-action="medication"', content)
        self.assertNotIn('onclick="handleTaskClick(', content)
        self.assertNotIn("window.handleTaskClick = handleTaskClick;", script_content)
        self.assertIn("function handleHomeTaskAction(event)", script_content)
        self.assertIn("document.addEventListener('click', handleHomeTaskAction);", script_content)

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
        self.assertIn("document.addEventListener('visibilitychange', handleHomeVisibilityChange);", script_content)
        self.assertIn("window.addEventListener('pagehide', handleHomePageHide);", script_content)
        self.assertIn("window.addEventListener('beforeunload', handleHomeBeforeUnload);", script_content)
        self.assertIn("async function consumeRefreshMarkersAndSync()", script_content)
        self.assertIn("const HOME_PLAN_REFRESH_MARKER_KEY = 'home_plan_refresh_marker';", script_content)
        self.assertIn("function readHomePlanRefreshMarker()", script_content)
        self.assertIn("function applyRecentCompletedFallbacks(plans)", script_content)
        self.assertIn("function requestPlanRefresh(reason, options)", script_content)
        self.assertIn("markFollowupCompletedFallback();", script_content)
        self.assertIn("refreshUrl.searchParams.set('_ts', String(Date.now()));", script_content)
        self.assertIn("cache: 'no-store'", script_content)

    def test_patient_home_refreshes_daily_plan_on_history_restore(self):
        script_path = Path(settings.BASE_DIR) / "static" / "web_patient" / "patient_home.js"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("function isHistoryRestore(event)", content)
        self.assertIn("navEntry.type === 'back_forward'", content)
        self.assertIn("nav.type === 2", content)
        self.assertIn("const markerResult = await consumeRefreshMarkersAndSync();", content)
        self.assertIn("const shouldRefreshPlans = !markerResult.refreshed;", content)
        self.assertNotIn(
            "const shouldRefreshPlans = !markerResult.refreshed && (historyRestored || hasHomeSuccessParam() || HOME_PAGE_WAS_HIDDEN || hasRecentCompletionMarker);",
            content,
        )
        self.assertIn(
            "await requestPlanRefresh('pageshow', { followupSubmitted: markerResult.followupSubmitted, force: true });",
            content,
        )

    def test_patient_home_plan_refresh_reuses_in_flight_request(self):
        script_path = Path(settings.BASE_DIR) / "static" / "web_patient" / "patient_home.js"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("let PLAN_REFRESH_IN_FLIGHT = null;", content)
        self.assertIn("if (PLAN_REFRESH_IN_FLIGHT) {", content)
        self.assertIn("if (options.force !== true && now - LAST_PLAN_REFRESH_AT < HOME_PLAN_REFRESH_THROTTLE_MS)", content)
        self.assertIn("PLAN_REFRESH_IN_FLIGHT = refreshMetricData(refreshOptions)", content)
        self.assertIn("PLAN_REFRESH_IN_FLIGHT = null;", content)

    def test_patient_home_success_param_whitelist_matches_home_refresh_params(self):
        script_path = Path(settings.BASE_DIR) / "static" / "web_patient" / "patient_home.js"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("const HOME_SUCCESS_PARAMS = [", content)
        for param in (
            "temperature",
            "bp_hr",
            "spo2",
            "weight",
            "breath_val",
            "sputum_val",
            "pain_val",
            "step",
            "medication_taken",
            "checkup_completed",
            "followup",
        ):
            self.assertIn(f"'{param}'", content)
        self.assertIn("function hasHomeSuccessParam()", content)
        self.assertIn("HOME_SUCCESS_PARAMS.some(function (param) {", content)

    def test_patient_home_marker_sync_reports_whether_it_refreshed(self):
        script_path = Path(settings.BASE_DIR) / "static" / "web_patient" / "patient_home.js"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("return { refreshed: false, followupSubmitted: followupSubmitted };", content)
        self.assertIn("return { refreshed: true, followupSubmitted: followupSubmitted };", content)
        self.assertIn("await requestPlanRefresh('legacy_marker', { followupSubmitted: followupSubmitted });", content)

    def test_patient_home_keeps_short_lived_completed_marker(self):
        script_path = Path(settings.BASE_DIR) / "static" / "web_patient" / "patient_home.js"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("const HOME_PLAN_REFRESH_MARKER_TTL_MS = 10 * 60 * 1000;", content)
        self.assertIn("completedTypes: completedTypes", content)
        self.assertIn("expiresAt: Date.now() + HOME_PLAN_REFRESH_MARKER_TTL_MS", content)
        self.assertIn("Array.isArray(marker.completedTypes)", content)
        self.assertIn("localStorage.removeItem(HOME_PLAN_REFRESH_MARKER_KEY);", content)
        self.assertIn("HOME_COMPLETED_FALLBACK_SUBTITLES[type]", content)
        self.assertIn("if (plan) {", content)
        self.assertIn("setPlanCardState(type, 'completed', subtitle);", content)
        self.assertNotIn("if (plan && plan.status === 'completed')", content)
        self.assertNotIn("checkup_all_completed", content)
        self.assertNotIn("CHECKUP_COMPLETION_UPDATED", content)

    def test_patient_home_dynamic_task_links_mark_every_task_as_home_source(self):
        script_path = Path(settings.BASE_DIR) / "static" / "web_patient" / "patient_home.js"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn("taskUrl.searchParams.set('source', 'home');", content)
        self.assertIn("taskUrl.searchParams.set('patient_id', PATIENT_ID);", content)
        self.assertNotIn("function handleTaskClick(", content)

    def test_metric_record_pages_replace_home_for_home_source(self):
        cases = {
            "record_temperature.html": "temperature=true",
            "record_bp.html": "bp_hr=true",
            "record_spo2.html": "spo2=true",
            "record_weight.html": "weight=true",
        }

        for template_name, success_param in cases.items():
            with self.subTest(template=template_name):
                template_path = Path(settings.BASE_DIR) / "templates" / "web_patient" / template_name
                content = template_path.read_text(encoding="utf-8")

                self.assertIn("const source = (urlParams.get('source') || '').trim();", content)
                self.assertIn("if (source === 'home') {", content)
                self.assertIn("function writeHomePlanRefreshMarker(type)", content)
                metric_type = success_param.split("=")[0]
                self.assertIn(f"writeHomePlanRefreshMarker('{metric_type}');", content)
                self.assertIn(
                    f'window.location.replace("{{% url \'web_patient:patient_home\' %}}?{success_param}");',
                    content,
                )
                self.assertIn("history.back();", content)

    def test_record_checkup_replaces_home_for_home_source(self):
        template_path = Path(settings.BASE_DIR) / "templates" / "web_patient" / "record_checkup.html"
        content = template_path.read_text(encoding="utf-8")

        self.assertIn('data-entry-source="{{ entry_source|default:\'\' }}"', content)
        self.assertIn("const pageRoot = document.querySelector('[data-entry-source]');", content)
        self.assertIn("return urlSource || rootSource;", content)
        self.assertIn("const entrySource = getEntrySource();", content)
        self.assertIn("function returnAfterCheckup(entrySource) {", content)
        self.assertIn("if (entrySource === 'home') {", content)
        self.assertIn("function writeHomePlanRefreshMarker(type)", content)
        self.assertIn("writeHomePlanRefreshMarker('checkup');", content)
        self.assertNotIn("const allCompleted = await refreshHomeCheckupStatus();", content)
        self.assertNotIn("async function refreshHomeCheckupStatus()", content)
        self.assertNotIn("localStorage.setItem('checkup_all_completed'", content)
        self.assertIn(
            "window.location.replace(HOME_CHECKUP_URL);",
            content,
        )
        self.assertIn("setTimeout(() => { returnAfterCheckup(entrySource); }, 300);", content)
        self.assertIn("history.back();", content)
        self.assertIn("window.location.href = HOME_URL;", content)

    def test_daily_survey_redirects_home_only_for_home_source(self):
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
        self.assertIn('id="finish-home-btn"', content)
        self.assertNotIn(
            '<a href="{% url \'web_patient:patient_home\' %}?followup=true&patient_id={{ patient_id }}"',
            content,
        )
        self.assertIn("function getEntrySource()", content)
        self.assertIn("function returnAfterSurvey(source)", content)
        self.assertIn("const source = (urlParams.get('source') || '').trim();", content)
        self.assertIn("if (source === 'home') {", content)
        self.assertIn("function writeHomePlanRefreshMarker(type)", content)
        self.assertIn("writeHomePlanRefreshMarker('followup');", content)
        self.assertIn(
            "window.location.replace(HOME_FOLLOWUP_URL);",
            content,
        )
        self.assertIn("setTimeout(() => { returnAfterSurvey(source); }, 300);", content)
        self.assertIn("history.back();", content)
        self.assertIn("window.location.href = HOME_URL;", content)
