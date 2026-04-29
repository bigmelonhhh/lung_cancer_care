from datetime import date, datetime, timedelta
from decimal import Decimal
from urllib.parse import urlencode

from django.contrib.auth import get_user_model
from django.test import tag
from django.urls import reverse
from django.utils import timezone

from chat.services.chat import ChatService
from core.models import (
    CheckupLibrary,
    Questionnaire,
    QuestionnaireCode,
    QuestionnaireOption,
    QuestionnaireQuestion,
    choices as core_choices,
)
from health_data.models import (
    HealthMetric,
    QuestionnaireAnswer,
    QuestionnaireSubmission,
    ReportImage,
    UploadSource,
)
from health_data.services.report_service import ReportUploadService
from patient_alerts.models import AlertEventType, AlertLevel, AlertStatus, PatientAlert
from tests.browser.web_doctor.base import DoctorBrowserTestCase, expect
from users import choices
from users.models import AssistantProfile, DoctorAssistantMap

User = get_user_model()


@tag("browser")
class DoctorMobilePagesBrowserTests(DoctorBrowserTestCase):
    def browser_context_options(self):
        return {
            "base_url": self.live_server_url,
            "viewport": {"width": 390, "height": 844},
            "is_mobile": True,
            "has_touch": True,
            "user_agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 "
                "Mobile/15E148 Safari/604.1"
            ),
        }

    def setUp(self):
        super().setUp()
        self.chat_service = ChatService()
        self.pending_alert = PatientAlert.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            event_type=AlertEventType.DATA,
            event_level=AlertLevel.MILD,
            event_title="体温异常待处理",
            event_content="请尽快随访",
            event_time=timezone.now(),
            status=AlertStatus.PENDING,
        )
        self.completed_alert = PatientAlert.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            event_type=AlertEventType.BEHAVIOR,
            event_level=AlertLevel.MODERATE,
            event_title="用药完成记录",
            event_content="已完成复核",
            event_time=timezone.now() - timedelta(hours=1),
            status=AlertStatus.COMPLETED,
            handler=self.doctor_user,
            handle_time=timezone.now() - timedelta(minutes=30),
            handle_content="医生已处理",
        )

    def _create_assistant(self):
        assistant_user = User.objects.create_user(
            username="browser_assistant",
            password="password",
            user_type=choices.UserType.ASSISTANT,
            phone="13800002001",
        )
        assistant = AssistantProfile.objects.create(
            user=assistant_user,
            name="Browser Assistant",
            status=choices.AssistantStatus.ACTIVE,
        )
        DoctorAssistantMap.objects.create(doctor=self.doctor, assistant=assistant)
        return assistant_user, assistant

    def _create_questionnaire_submission(self):
        questionnaire, _ = Questionnaire.objects.get_or_create(
            code=QuestionnaireCode.Q_ANXIETY,
            defaults={"name": "焦虑评估", "is_active": True},
        )
        question = QuestionnaireQuestion.objects.create(
            questionnaire=questionnaire,
            text="最近是否感到紧张？",
            q_type=core_choices.QuestionType.SINGLE,
            seq=1,
            is_required=True,
        )
        option = QuestionnaireOption.objects.create(
            question=question,
            text="经常",
            score=Decimal("3.00"),
            seq=1,
        )
        submission = QuestionnaireSubmission.objects.create(
            patient=self.patient,
            questionnaire=questionnaire,
            total_score=Decimal("3.00"),
        )
        QuestionnaireAnswer.objects.create(submission=submission, question=question, option=option)
        HealthMetric.objects.create(
            patient=self.patient,
            metric_type=QuestionnaireCode.Q_ANXIETY,
            measured_at=timezone.make_aware(datetime(2025, 3, 10, 10, 0)),
            value_main=Decimal("3.00"),
            source="manual",
            questionnaire_submission=submission,
        )
        return submission

    def test_mobile_home_loads_and_links_to_patient_list(self):
        self.page.goto(self.url_for("web_doctor:mobile_home"), wait_until="domcontentloaded")

        expect(self.page.locator("body")).to_contain_text("Browser Doctor")
        expect(self.page.locator("body")).to_contain_text("管理患者")
        expect(self.page.locator("body")).to_contain_text("异常警报")

        self.page.get_by_text("患者管理").click()
        expect(self.page.locator("body")).to_contain_text("患者列表", timeout=10000)
        expect(self.page.locator('[data-patient-item][data-patient-id="%s"]' % self.patient.id)).to_be_visible()

    def test_mobile_patient_list_search_and_open_patient_home(self):
        self.page.goto(self.url_for("web_doctor:mobile_patient_list"), wait_until="domcontentloaded")

        expect(self.page.locator("body")).to_contain_text("患者列表")
        expect(self.page.locator('[data-patient-item][data-patient-id="%s"]' % self.patient.id)).to_be_visible()

        self.page.locator('input[name="q"]').fill("Browser Patient")
        self.page.get_by_role("button", name="搜索").click()
        expect(self.page.locator("body")).to_contain_text("当前搜索：Browser Patient", timeout=10000)

        self.page.locator('[data-patient-item][data-patient-id="%s"]' % self.patient.id).click()
        expect(self.page.locator("body")).to_contain_text("患者：Browser Patient", timeout=10000)
        expect(self.page.locator("body")).to_contain_text("常用菜单")

    def test_mobile_patient_home_menu_entries_navigate(self):
        self.page.goto(
            self.url_for("web_doctor:mobile_patient_home", self.patient.id),
            wait_until="domcontentloaded",
        )

        expect(self.page.locator("#mobile-patient-home-content")).to_be_visible(timeout=10000)
        expect(self.page.get_by_text("基本信息")).to_be_visible()
        expect(self.page.get_by_text("管理指标")).to_be_visible()
        expect(self.page.get_by_text("患者待办")).to_be_visible()

        self.page.get_by_text("患者待办").click()
        expect(self.page.locator("body")).to_contain_text("患者待办：Browser Patient", timeout=10000)
        expect(self.page.locator("body")).to_contain_text("体温异常待处理")

    def test_mobile_todo_detail_modal_opens_and_closes(self):
        self.page.goto(
            self.url_for("web_doctor:mobile_patient_todo_list")
            + "?patient_id=%s" % self.patient.id,
            wait_until="domcontentloaded",
        )

        expect(self.page.locator("#mobile-todo-list-content")).to_contain_text("体温异常待处理")
        self.page.locator('[data-test="todo-action-view"]').first.click()

        modal = self.page.locator("#todo-detail-modal")
        expect(modal).to_be_visible(timeout=10000)
        expect(modal).to_contain_text("体温异常待处理")
        expect(self.page.locator("#todo-detail-save")).to_be_hidden()

        self.page.locator("#todo-detail-close").click()
        expect(modal).to_be_hidden(timeout=10000)

    def test_mobile_patient_basic_info_loads_api_sections(self):
        url = (
            self.url_for("web_doctor:mobile_patient_basic_info")
            + "?patient_id=%s" % self.patient.id
        )
        self.page.goto(url, wait_until="domcontentloaded")

        expect(self.page.locator("body")).to_contain_text("基本信息")
        expect(self.page.locator("body")).to_contain_text("亲情账号")
        expect(self.page.locator("body")).to_contain_text("病情信息")
        expect(self.page.locator("#basic-info-content")).to_be_visible(timeout=10000)
        expect(self.page.locator("#basic-name")).to_contain_text("Browser Patient")
        expect(self.page.locator("#medical-content")).to_be_visible(timeout=10000)
        expect(self.page.locator("#member-content")).to_be_visible(timeout=10000)

    def test_mobile_health_records_and_metric_detail_load(self):
        records_url = (
            self.url_for("web_doctor:mobile_health_records")
            + "?patient_id=%s" % self.patient.id
        )
        self.page.goto(records_url, wait_until="domcontentloaded")

        expect(self.page.locator("body")).to_contain_text("健康档案")
        expect(self.page.locator("body")).to_contain_text("一般监测指标")
        expect(self.page.get_by_role("button", name="查看详情").first).to_be_visible()

        detail_url = (
            self.url_for("web_doctor:mobile_health_record_detail")
            + "?"
            + urlencode(
                {
                    "type": "temperature",
                    "title": "体温",
                    "patient_id": self.patient.id,
                    "month": "2025-03",
                }
            )
        )
        self.page.goto(detail_url, wait_until="domcontentloaded")

        expect(self.page.locator("body")).to_contain_text("体温")
        expect(self.page.locator("#record-list-wrapper")).to_be_visible()
        expect(self.page.locator("#chart-switch-btn")).to_be_visible()
        expect(self.page.locator("#empty-state")).to_contain_text("暂无记录")

    def test_mobile_patient_records_page_loads_empty_state(self):
        self.page.goto(
            self.url_for("web_doctor:mobile_patient_records", self.patient.id),
            wait_until="domcontentloaded",
        )

        expect(self.page.locator("body")).to_contain_text("诊疗记录")
        expect(self.page.locator("body")).to_contain_text("暂无诊疗记录")

    def test_mobile_patient_chat_and_internal_chat_pages_load(self):
        self.chat_service.get_or_create_patient_conversation(
            patient=self.patient,
            studio=self.studio,
            operator=self.doctor_user,
        )

        self.page.goto(
            self.url_for("web_doctor:mobile_patient_chat_list", self.patient.id),
            wait_until="domcontentloaded",
        )

        expect(self.page.locator("body")).to_contain_text("聊天记录：Browser Patient")
        expect(self.page.locator('[data-test="mobile-internal-chat-fab"]')).to_be_visible()

        self.page.locator('[data-test="mobile-internal-chat-fab"]').click()
        expect(self.page.locator("body")).to_contain_text("内部沟通：医生助理", timeout=10000)
        expect(self.page.locator("body")).to_contain_text("Browser Patient")
        expect(self.page.locator('[data-test="mobile-internal-chat-input"]')).to_be_visible()
        expect(self.page.locator('[data-test="mobile-internal-send-btn"]')).to_be_visible()

    def test_mobile_my_assistant_lists_linked_assistant(self):
        self._create_assistant()

        self.page.goto(self.url_for("web_doctor:mobile_my_assistant"), wait_until="domcontentloaded")

        expect(self.page.locator("body")).to_contain_text("我的助理")
        expect(self.page.locator("body")).to_contain_text("助理成员")
        expect(self.page.locator("body")).to_contain_text("Browser Assistant")

    def test_mobile_related_doctors_loads_for_assistant_account(self):
        assistant_user, _assistant = self._create_assistant()
        self.login_browser_as(assistant_user)

        self.page.goto(
            self.url_for("web_doctor:mobile_related_doctors"),
            wait_until="domcontentloaded",
        )

        expect(self.page.locator("body")).to_contain_text("关联医生")
        expect(self.page.locator("body")).to_contain_text("Browser Doctor")
        expect(self.page.locator("body")).to_contain_text("主任医师")

    def test_mobile_questionnaire_submission_detail_loads_answers(self):
        submission = self._create_questionnaire_submission()
        detail_url = self.url_for(
            "web_doctor:mobile_questionnaire_submission_detail",
            submission.id,
        )
        next_url = (
            self.url_for("web_doctor:mobile_health_record_detail")
            + "?"
            + urlencode(
                {
                    "type": "anxiety",
                    "title": "焦虑评估",
                    "patient_id": self.patient.id,
                    "month": "2025-03",
                }
            )
        )

        self.page.goto(
            detail_url + "?patient_id=%s&next=%s" % (self.patient.id, next_url),
            wait_until="domcontentloaded",
        )

        expect(self.page.locator("body")).to_contain_text("焦虑评估")
        expect(self.page.locator("body")).to_contain_text("最近是否感到紧张？")
        expect(self.page.locator("body")).to_contain_text("经常")

    def test_mobile_review_record_detail_loads_initial_archive(self):
        checkup_item = CheckupLibrary.objects.create(name="胸部CT", code="browser_ct")
        ReportUploadService.create_upload(
            self.patient,
            images=[
                {
                    "image_url": "https://example.com/browser-ct.png",
                    "record_type": ReportImage.RecordType.CHECKUP,
                    "checkup_item_id": checkup_item.id,
                    "report_date": date(2025, 3, 28),
                }
            ],
            upload_source=UploadSource.CHECKUP_PLAN,
        )
        review_url = (
            self.url_for("web_doctor:mobile_review_record_detail")
            + "?"
            + urlencode(
                {
                    "patient_id": self.patient.id,
                    "category_code": checkup_item.code,
                    "title": "胸部CT",
                    "month": "2025-03",
                }
            )
        )

        self.page.goto(review_url, wait_until="domcontentloaded")

        expect(self.page.locator("body")).to_contain_text("胸部CT")
        expect(self.page.locator("#rrd-month-picker")).to_be_attached()
        expect(self.page.locator("#rrd-scroll")).to_be_visible()
        expect(self.page.locator("#rrd-virtual-inner")).to_be_attached()
