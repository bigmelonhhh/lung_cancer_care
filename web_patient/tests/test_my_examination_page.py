from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import DailyTask, TreatmentCycle
from core.models import choices as core_choices
from core.models.choices import PlanItemCategory, TaskStatus
from market.models import Order, Product
from users.models import CustomUser, PatientProfile


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
        DailyTask.objects.create(
            patient=self.patient,
            task_date=today,
            task_type=PlanItemCategory.CHECKUP,
            title="同日已完成复查",
            status=TaskStatus.COMPLETED,
        )

        resp = self.client.get(reverse("web_patient:my_examination"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "我的复查")
        self.assertContains(resp, cycle.name)
        self.assertContains(resp, "复查")
        sections = {
            section["key"]: section
            for section in resp.context["treatment_course_sections"]
        }
        self.assertTrue(sections["in_progress"]["default_open"])
        self.assertEqual(
            sections["in_progress"]["courses"][0]["items"][0]["type"],
            "checkup",
        )
        self.assertEqual(
            len(sections["in_progress"]["courses"][0]["items"]),
            1,
        )

    def test_my_examination_excludes_questionnaires_and_keeps_empty_courses(self):
        today = timezone.localdate()
        cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="仅问卷疗程",
            start_date=today - timedelta(days=2),
            end_date=today + timedelta(days=18),
            cycle_days=21,
            status=core_choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        DailyTask.objects.create(
            patient=self.patient,
            task_date=today,
            task_type=PlanItemCategory.QUESTIONNAIRE,
            title="问卷提醒",
            status=TaskStatus.PENDING,
        )

        response = self.client.get(reverse("web_patient:my_examination"))

        self.assertEqual(response.status_code, 200)
        current_section = response.context["treatment_course_sections"][0]
        self.assertEqual(current_section["courses"][0]["name"], cycle.name)
        self.assertEqual(current_section["courses"][0]["items"], [])
        self.assertContains(response, "该疗程暂无复查计划")
        self.assertNotContains(response, "问卷提醒")

    def test_my_examination_empty_sections_render_page_specific_empty_states(self):
        response = self.client.get(reverse("web_patient:my_examination"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [section["count"] for section in response.context["treatment_course_sections"]],
            [0, 0, 0],
        )
        self.assertContains(response, "暂无进行中疗程")
        self.assertContains(response, "当前没有正在执行的复查计划")

    @patch(
        "web_patient.views.my_examination.build_checkup_course_sections",
        side_effect=RuntimeError("query failed"),
    )
    def test_my_examination_query_failure_logs_and_renders_error(self, mock_build):
        with self.assertLogs("web_patient.views.my_examination", level="ERROR"):
            response = self.client.get(reverse("web_patient:my_examination"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "复查数据加载失败，请稍后重试。")
        self.assertEqual(
            [section["count"] for section in response.context["treatment_course_sections"]],
            [0, 0, 0],
        )
        mock_build.assert_called_once()
