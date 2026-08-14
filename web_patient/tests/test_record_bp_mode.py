from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from django.db import IntegrityError
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from core.models import DailyTask, MonitoringTemplate, PlanItem, TreatmentCycle
from core.models import choices as core_choices
from core.models import Questionnaire
from core.models.questionnaire import QuestionnaireCode
from health_data.models import HealthMetric, MetricType
from market.models import Order, Product
from users.models import CustomUser, PatientProfile


class RecordBpModeTests(TestCase):
    """血压/心率共用录入页 mode 参数（both/bp/heart）行为测试。"""

    def setUp(self):
        self.client = Client()
        self.user = CustomUser.objects.create_user(
            username="testpatient_bp_mode",
            password="password",
            wx_openid="test_openid_bp_mode",
        )
        self.patient = PatientProfile.objects.create(user=self.user, name="Test Patient")
        self.client.force_login(self.user)
        self.url = reverse("web_patient:record_bp")

    def test_mode_bp_post_saves_only_blood_pressure(self):
        """mode=bp 时仅校验并保存血压，不要求心率。"""
        response = self.client.post(
            self.url,
            {
                "mode": "bp",
                "ssy": "120",
                "szy": "80",
                "record_time": "2026-01-11 19:46",
                "record_time_touched": "1",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            HealthMetric.objects.filter(
                patient=self.patient, metric_type=MetricType.BLOOD_PRESSURE
            ).exists()
        )
        self.assertFalse(
            HealthMetric.objects.filter(
                patient=self.patient, metric_type=MetricType.HEART_RATE
            ).exists()
        )

    def test_mode_heart_post_saves_only_heart_rate(self):
        """mode=heart 时仅校验并保存心率，不要求血压。"""
        response = self.client.post(
            self.url,
            {
                "mode": "heart",
                "heart": "75",
                "record_time": "2026-01-11 19:46",
                "record_time_touched": "1",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            HealthMetric.objects.filter(
                patient=self.patient, metric_type=MetricType.HEART_RATE
            ).exists()
        )
        self.assertFalse(
            HealthMetric.objects.filter(
                patient=self.patient, metric_type=MetricType.BLOOD_PRESSURE
            ).exists()
        )

    def test_mode_bp_ajax_missing_required_returns_400(self):
        """mode=bp 缺必填字段时 AJAX 返回 400 JSON。"""
        response = self.client.post(
            self.url,
            {"mode": "bp", "ssy": "120"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["status"], "error")

    def test_mode_heart_ajax_missing_required_returns_400(self):
        """mode=heart 缺心率时 AJAX 返回 400 JSON。"""
        response = self.client.post(
            self.url,
            {"mode": "heart"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["status"], "error")

    def test_mode_bp_ajax_rejects_out_of_range_values(self):
        response = self.client.post(
            self.url,
            {"mode": "bp", "ssy": "-1", "szy": "999"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["status"], "error")
        self.assertFalse(HealthMetric.objects.filter(patient=self.patient).exists())

    def test_mode_heart_ajax_rejects_out_of_range_value(self):
        response = self.client.post(
            self.url,
            {"mode": "heart", "heart": "201"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["status"], "error")
        self.assertFalse(HealthMetric.objects.filter(patient=self.patient).exists())

    def test_mode_bp_ajax_rejects_reversed_pressure_values(self):
        response = self.client.post(
            self.url,
            {"mode": "bp", "ssy": "80", "szy": "120"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["status"], "error")
        self.assertFalse(HealthMetric.objects.filter(patient=self.patient).exists())

    def test_default_mode_both_still_requires_all_fields(self):
        """不带 mode 时保持存量行为：三字段齐全才落库。"""
        response = self.client.post(
            self.url,
            {
                "ssy": "120",
                "szy": "80",
                "record_time": "2026-01-11 19:46",
                "record_time_touched": "1",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            HealthMetric.objects.filter(
                patient=self.patient, metric_type=MetricType.BLOOD_PRESSURE
            ).exists()
        )

    def test_mode_heart_get_hides_bp_fields(self):
        """mode=heart 页面不渲染血压输入框。"""
        response = self.client.get(self.url, {"mode": "heart"})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="ssy"')
        self.assertNotContains(response, 'name="szy"')
        self.assertContains(response, 'name="heart"')
        self.assertContains(response, "录入心率")

    def test_mode_bp_get_hides_heart_field(self):
        """mode=bp 页面不渲染心率输入框。"""
        response = self.client.get(self.url, {"mode": "bp"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="ssy"')
        self.assertNotContains(response, 'name="heart"')
        self.assertContains(response, "录入血压")

    def test_invalid_mode_falls_back_to_both(self):
        """非法 mode 回落 both，页面渲染全部字段。"""
        response = self.client.get(self.url, {"mode": "hacker"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["mode"], "both")
        self.assertContains(response, 'name="ssy"')
        self.assertContains(response, 'name="heart"')


class HeartRecordDetailAddButtonTests(TestCase):
    """心率档案详情页应显示新增数据按钮。"""

    def setUp(self):
        self.client = Client()
        self.user = CustomUser.objects.create_user(
            username="testpatient_heart_detail",
            password="password",
            wx_openid="test_openid_heart_detail",
        )
        self.patient = PatientProfile.objects.create(user=self.user, name="Test Patient")
        self.client.force_login(self.user)
        self.url = reverse("web_patient:health_record_detail")

    def test_heart_detail_from_health_records_shows_add_button(self):
        response = self.client.get(
            self.url,
            {
                "type": "heart",
                "title": "心率",
                "source": "health_records",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["show_add_button"])
        self.assertContains(response, "新增数据")

    def test_bp_detail_from_health_records_still_shows_add_button(self):
        response = self.client.get(
            self.url,
            {
                "type": "bp",
                "title": "血压",
                "source": "health_records",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["show_add_button"])
        self.assertContains(response, "新增数据")


class BpHrBothRequiredCompletionTests(TestCase):
    """血压/心率计划以当日双项齐全才算完成；单项录入仅新增数据。"""

    def setUp(self):
        cache.clear()
        self.client = Client()
        self.user = CustomUser.objects.create_user(
            username="testpatient_bp_hr_both",
            password="password",
            wx_openid="test_openid_bp_hr_both",
        )
        self.patient = PatientProfile.objects.create(
            user=self.user, name="Test Patient", phone="13900000012"
        )
        self.client.force_login(self.user)
        self.url = reverse("web_patient:record_bp")

        product = Product.objects.create(
            name="VIP 服务包",
            price=Decimal("199.00"),
            duration_days=30,
            is_active=True,
        )
        Order.objects.create(
            patient=self.patient,
            product=product,
            amount=Decimal("199.00"),
            status=Order.Status.PAID,
            paid_at=timezone.now(),
        )
        self.today = timezone.localdate()
        cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="血压心率双项疗程",
            start_date=self.today - timedelta(days=3),
            end_date=self.today + timedelta(days=3),
            cycle_days=7,
            status=core_choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        self.task_ids = []
        for metric_type, title in (
            (MetricType.BLOOD_PRESSURE, "血压监测"),
            (MetricType.HEART_RATE, "心率监测"),
        ):
            template, _ = MonitoringTemplate.objects.get_or_create(
                code=metric_type,
                defaults={
                    "name": title,
                    "metric_type": metric_type,
                    "is_active": True,
                },
            )
            plan_item = PlanItem.objects.create(
                cycle=cycle,
                category=core_choices.PlanItemCategory.MONITORING,
                template_id=template.id,
                item_name=title,
                schedule_days=[1],
                status=core_choices.PlanItemStatus.ACTIVE,
            )
            self.task_ids.append(
                DailyTask.objects.create(
                    patient=self.patient,
                    plan_item=plan_item,
                    task_date=self.today,
                    task_type=core_choices.PlanItemCategory.MONITORING,
                    title=title,
                    status=core_choices.TaskStatus.PENDING,
                ).id
            )

    def _task_statuses(self):
        tasks = DailyTask.objects.filter(id__in=self.task_ids).order_by("id")
        return [task.status for task in tasks]

    def test_single_bp_entry_only_adds_data_without_completing_tasks(self):
        response = self.client.post(
            self.url,
            {"mode": "bp", "ssy": "120", "szy": "80", "record_time_touched": "0"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            HealthMetric.objects.filter(
                patient=self.patient, metric_type=MetricType.BLOOD_PRESSURE
            ).exists()
        )
        self.assertEqual(
            self._task_statuses(),
            [core_choices.TaskStatus.PENDING, core_choices.TaskStatus.PENDING],
        )

    def test_single_heart_entry_only_adds_data_without_completing_tasks(self):
        response = self.client.post(
            self.url,
            {"mode": "heart", "heart": "75", "record_time_touched": "0"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            HealthMetric.objects.filter(
                patient=self.patient, metric_type=MetricType.HEART_RATE
            ).exists()
        )
        self.assertEqual(
            self._task_statuses(),
            [core_choices.TaskStatus.PENDING, core_choices.TaskStatus.PENDING],
        )

    def test_both_entry_completes_bp_and_heart_tasks(self):
        response = self.client.post(
            self.url,
            {
                "ssy": "120",
                "szy": "80",
                "heart": "75",
                "record_time_touched": "0",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self._task_statuses(),
            [core_choices.TaskStatus.COMPLETED, core_choices.TaskStatus.COMPLETED],
        )

    def test_query_last_metric_bp_hr_requires_both_metrics(self):
        # 仅录心率：计划保持 pending。
        self.client.post(
            self.url,
            {"mode": "heart", "heart": "75", "record_time_touched": "0"},
        )
        response = self.client.get(reverse("web_patient:query_last_metric"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["plans"]["bp_hr"]["status"], "pending")

        # 再走双项录入：计划变为 completed 且副标题含双项数值。
        self.client.post(
            self.url,
            {
                "ssy": "120",
                "szy": "80",
                "heart": "78",
                "record_time_touched": "0",
            },
        )
        response = self.client.get(reverse("web_patient:query_last_metric"))
        self.assertEqual(response.status_code, 200)
        bp_hr = response.json()["plans"]["bp_hr"]
        self.assertEqual(bp_hr["status"], "completed")
        self.assertIn("血压120/80mmHg", bp_hr["subtitle"])
        self.assertIn("心率7", bp_hr["subtitle"])

    def test_patient_home_bp_hr_requires_both_metrics(self):
        # 仅录血压：首页 bp_hr 计划保持 pending。
        self.client.post(
            self.url,
            {"mode": "bp", "ssy": "120", "szy": "80", "record_time_touched": "0"},
        )
        cache.clear()
        response = self.client.get(reverse("web_patient:patient_home"))
        self.assertEqual(response.status_code, 200)
        daily_plans = response.context.get("daily_plans") or []
        bp_hr_plan = next((p for p in daily_plans if p.get("type") == "bp_hr"), None)
        self.assertIsNotNone(bp_hr_plan)
        self.assertEqual(bp_hr_plan["status"], "pending")

        # 补齐心率（单项）后双项齐全：首页计划变为 completed。
        self.client.post(
            self.url,
            {"mode": "heart", "heart": "75", "record_time_touched": "0"},
        )
        cache.clear()
        response = self.client.get(reverse("web_patient:patient_home"))
        self.assertEqual(response.status_code, 200)
        daily_plans = response.context.get("daily_plans") or []
        bp_hr_plan = next((p for p in daily_plans if p.get("type") == "bp_hr"), None)
        self.assertIsNotNone(bp_hr_plan)
        self.assertEqual(bp_hr_plan["status"], "completed")
        self.assertIn("血压", bp_hr_plan["subtitle"])
        self.assertIn("心率", bp_hr_plan["subtitle"])

        # 两次单项补录已经满足双项计划，底层任务与其他页面必须同步完成。
        self.assertEqual(
            self._task_statuses(),
            [core_choices.TaskStatus.COMPLETED, core_choices.TaskStatus.COMPLETED],
        )
        tasks = list(
            DailyTask.objects.filter(id__in=self.task_ids).select_related("plan_item")
        )
        template_codes = dict(
            MonitoringTemplate.objects.filter(
                id__in=[task.plan_item.template_id for task in tasks]
            ).values_list("id", "code")
        )
        task_ids_by_type = {
            template_codes[task.plan_item.template_id]: task.id for task in tasks
        }
        metric_task_ids = dict(
            HealthMetric.objects.filter(
                patient=self.patient,
                metric_type__in=(
                    MetricType.BLOOD_PRESSURE,
                    MetricType.HEART_RATE,
                ),
            ).values_list("metric_type", "task_id")
        )
        self.assertEqual(metric_task_ids, task_ids_by_type)

        management_response = self.client.get(reverse("web_patient:management_plan"))
        management_item = next(
            item
            for item in management_response.context["monitoring_plan"]
            if item["title"] == "测量血压/心率"
        )
        self.assertEqual(management_item["status"], "completed")

        calendar_response = self.client.get(
            reverse("web_patient:health_calendar"),
            {"date": self.today.strftime("%Y-%m-%d")},
        )
        calendar_item = next(
            item
            for item in calendar_response.context["daily_plans"]
            if item["type"] == "bp_hr"
        )
        self.assertEqual(calendar_item["status"], "completed")

    def test_both_entry_rolls_back_when_second_metric_write_fails(self):
        """双项录入任一指标保存失败时，不留下半套指标或已完成任务。"""
        original_create = HealthMetric.objects.create

        def create_metric_or_fail(**kwargs):
            if kwargs.get("metric_type") == MetricType.HEART_RATE:
                raise IntegrityError("模拟心率写入失败")
            return original_create(**kwargs)

        with patch(
            "health_data.models.HealthMetric.objects.create",
            side_effect=create_metric_or_fail,
        ):
            response = self.client.post(
                self.url,
                {
                    "ssy": "120",
                    "szy": "80",
                    "heart": "75",
                    "record_time_touched": "0",
                },
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )

        self.assertEqual(response.status_code, 500)
        self.assertFalse(HealthMetric.objects.filter(patient=self.patient).exists())
        self.assertEqual(
            self._task_statuses(),
            [core_choices.TaskStatus.PENDING, core_choices.TaskStatus.PENDING],
        )


class HeartRecordLabelEditTests(TestCase):
    """心率档案：列表/弹框去评分提示，编辑保存实际生效。"""

    def setUp(self):
        cache.clear()
        self.client = Client()
        self.user = CustomUser.objects.create_user(
            username="testpatient_heart_label",
            password="password",
            wx_openid="test_openid_heart_label",
        )
        self.patient = PatientProfile.objects.create(user=self.user, name="Test Patient")
        self.client.force_login(self.user)
        # cough 等问卷类型属会员专属，需开通会员才能访问详情页
        product = Product.objects.create(
            name="VIP 服务包",
            price=Decimal("199.00"),
            duration_days=30,
            is_active=True,
        )
        Order.objects.create(
            patient=self.patient,
            product=product,
            amount=Decimal("199.00"),
            status=Order.Status.PAID,
            paid_at=timezone.now(),
        )
        self.metric = HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.HEART_RATE,
            value_main=Decimal("88"),
            measured_at=timezone.now(),
            source="manual",
        )

    def test_heart_record_label_has_no_score_hint(self):
        response = self.client.get(
            reverse("web_patient:health_record_detail"),
            {"type": "heart", "title": "心率", "source": "health_records"},
        )
        self.assertEqual(response.status_code, 200)
        field = response.context["records"][0]["data"][0]
        self.assertEqual(field["label"], "心率")
        self.assertEqual(field["key"], "heart")
        self.assertEqual(field["unit"], "bpm")
        self.assertNotContains(response, "（评分）")
        self.assertContains(response, 'unit: "bpm"')

    def test_questionnaire_record_label_keeps_score_hint(self):
        # 迁移预置了 Q_COUGH 问卷，会员会走动态问卷详情页；
        # 删除后回退到 HealthMetric 列表分支，验证评分提示仍保留。
        Questionnaire.objects.filter(code=QuestionnaireCode.Q_COUGH).delete()
        HealthMetric.objects.create(
            patient=self.patient,
            metric_type=QuestionnaireCode.Q_COUGH,
            value_main=Decimal("2"),
            measured_at=timezone.now(),
            source="manual",
        )
        response = self.client.get(
            reverse("web_patient:health_record_detail"),
            {"type": "cough", "title": "咳嗽"},
        )
        self.assertEqual(response.status_code, 200)
        field = response.context["records"][0]["data"][0]
        self.assertEqual(field["label"], "咳嗽（评分）")
        self.assertEqual(field["key"], "common")

    def test_update_heart_metric_via_edit_api_persists(self):
        response = self.client.post(
            reverse("web_patient:update_health_metric"),
            {"id": self.metric.id, "value_main": "90"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.metric.refresh_from_db()
        self.assertEqual(self.metric.value_main, Decimal("90"))

        detail = self.client.get(
            reverse("web_patient:health_record_detail"),
            {"type": "heart", "title": "心率", "source": "health_records"},
        )
        self.assertContains(detail, "90 bpm")
