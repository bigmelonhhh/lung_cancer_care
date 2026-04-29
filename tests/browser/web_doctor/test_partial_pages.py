from datetime import timedelta

from django.test import tag
from django.utils import timezone

from patient_alerts.models import AlertEventType, AlertLevel, AlertStatus, PatientAlert
from tests.browser.web_doctor.base import DoctorBrowserTestCase, expect


@tag("browser")
class DoctorPartialPagesBrowserTests(DoctorBrowserTestCase):
    def setUp(self):
        super().setUp()
        self.pending_alert = PatientAlert.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            event_type=AlertEventType.DATA,
            event_level=AlertLevel.MILD,
            event_title="桌面端待办待处理",
            event_content="请在桌面端完成随访",
            event_time=timezone.now(),
            status=AlertStatus.PENDING,
        )
        self.completed_alert = PatientAlert.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            event_type=AlertEventType.BEHAVIOR,
            event_level=AlertLevel.MODERATE,
            event_title="桌面端已处理待办",
            event_content="历史处理记录",
            event_time=timezone.now() - timedelta(hours=2),
            status=AlertStatus.COMPLETED,
            handler=self.doctor_user,
            handle_time=timezone.now() - timedelta(hours=1),
            handle_content="已处理",
        )

    def _section_url(self, section, query=""):
        url = self.url_for("web_doctor:patient_workspace_section", self.patient.id, section)
        if query:
            url += "?" + query
        return url

    def test_home_partial_loads_overview_medication_checkup_and_reports(self):
        self.page.goto(self._section_url("home"), wait_until="domcontentloaded")

        expect(self.page.locator("body")).to_contain_text("概况")
        expect(self.page.locator("body")).to_contain_text("当前用药")
        expect(self.page.locator("body")).to_contain_text("复查/诊疗")
        expect(self.page.locator("body")).to_contain_text("当前暂无正在进行的用药方案")

        self.page.locator("#patient-remark-display button").click()
        modal = self.page.locator("#edit-remark-modal")
        expect(modal).to_be_visible(timeout=10000)
        expect(modal).to_contain_text("编辑备注")

        modal.locator('button[type="button"]').first.click()
        expect(modal).to_be_hidden(timeout=10000)

    def test_history_partials_load_from_workspace_routes(self):
        self.page.goto(self._section_url("medical_history"), wait_until="domcontentloaded")
        expect(self.page.locator("body")).to_contain_text("病情历史记录")
        expect(self.page.locator("body")).to_contain_text("暂无历史记录")

        self.page.goto(self._section_url("medication_history"), wait_until="domcontentloaded")
        expect(self.page.locator("body")).to_contain_text("历史用药方案")
        expect(self.page.locator("body")).to_contain_text("暂无用药数据")

        self.page.goto(self._section_url("checkup_history"), wait_until="domcontentloaded")
        expect(self.page.locator("body")).to_contain_text("复查/诊疗历史记录")
        expect(self.page.locator("body")).to_contain_text("记录类型")
        expect(self.page.get_by_role("button", name="搜索")).to_be_visible()

    def test_indicators_and_questionnaire_detail_partials_load(self):
        self.page.goto(self._section_url("indicators"), wait_until="domcontentloaded")

        expect(self.page.locator("#indicators-wrapper")).to_be_visible(timeout=10000)
        expect(self.page.locator("body")).to_contain_text("常规监测指标")
        expect(self.page.locator("body")).to_contain_text("随访问卷")

        self.page.goto(
            self.url_for("web_doctor:questionnaire_detail", self.patient.id),
            wait_until="domcontentloaded",
        )
        expect(self.page.locator("body")).to_contain_text("随访问卷详情")
        expect(self.page.locator("#sidebar-container")).to_be_visible()
        expect(self.page.locator("#detail-container")).to_be_visible()
        expect(self.page.locator("body")).to_contain_text("暂无")

    def test_management_statistics_partials_load(self):
        self.page.goto(self._section_url("statistics"), wait_until="domcontentloaded")

        expect(self.page.locator("body")).to_contain_text("患者服务包")
        expect(self.page.locator("body")).to_contain_text("管理数据概览")
        expect(self.page.locator("body")).to_contain_text("管理数据统计")
        expect(self.page.locator("body")).to_contain_text("咨询数据统计")

    def test_todo_list_and_patient_sidebar_partials_load(self):
        todo_url = (
            self.url_for("web_doctor:doctor_todo_list")
            + "?patient_id=%s" % self.patient.id
        )
        self.page.goto(todo_url, wait_until="domcontentloaded")

        expect(self.page.locator("body")).to_contain_text("患者待办")
        expect(self.page.locator("#todo-table-container")).to_be_visible()
        expect(self.page.locator("body")).to_contain_text("桌面端待办待处理")
        expect(self.page.locator("#todo-table-body")).to_contain_text("去查看")

        self.page.goto(
            self.url_for("web_doctor:patient_todo_sidebar", self.patient.id),
            wait_until="domcontentloaded",
        )
        expect(self.page.locator("#patient-todo-list")).to_be_visible()
        expect(self.page.locator("body")).to_contain_text("Browser Patient的待办")
        expect(self.page.locator("body")).to_contain_text("桌面端待办待处理")
        expect(self.page.locator("body")).to_contain_text("待办列表")

    def test_reports_records_and_create_modal_partials_load(self):
        self.page.goto(
            self._section_url("reports", "tab=records"),
            wait_until="domcontentloaded",
        )

        expect(self.page.get_by_test_id("reports-history-content")).to_be_visible(timeout=10000)
        expect(self.page.locator("#consultation-records-root")).to_be_visible()
        expect(self.page.locator("body")).to_contain_text("记录类型")
        expect(self.page.locator("body")).to_contain_text("新增记录")
        expect(self.page.locator("body")).to_contain_text("暂无诊疗记录")

        self.open_patient_workspace()
        self.page.get_by_test_id("workspace-tab-reports").click()
        expect(self.page.locator("#consultation-records-root")).to_be_visible(timeout=10000)
        self.page.locator("#consultation-records-root").get_by_text("新增记录").click()

        expect(self.page.locator("body")).to_contain_text("新增诊疗记录")
        expect(self.page.locator("body")).to_contain_text("报告日期")
        expect(self.page.locator("body")).to_contain_text("报告图片")
