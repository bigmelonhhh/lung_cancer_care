from datetime import timedelta

from django.test import tag
from django.utils import timezone

from chat.models import Conversation, ConversationType, Message, MessageSenderRole
from core.models import TreatmentCycle, choices
from tests.browser.web_doctor.base import DoctorBrowserTestCase, expect


@tag("browser")
class DoctorCorePagesBrowserTests(DoctorBrowserTestCase):
    def test_workspace_search_and_patient_selection_load_home(self):
        self.open_doctor_workspace()

        expect(self.page.locator("#patient-list-container")).to_contain_text("Browser Patient")
        self.page.locator("#patient-search-input").fill("Browser Patient")
        self.page.locator("#patient-search-btn").click()
        expect(self.page.locator('[data-patient-item][data-patient-id="%s"]' % self.patient.id)).to_be_visible()

        self.page.locator('[data-patient-item][data-patient-id="%s"]' % self.patient.id).click()
        expect(self.page.locator("#patient-content")).to_contain_text("概况", timeout=10000)
        expect(self.page.get_by_test_id("workspace-tab-home")).to_be_visible(timeout=10000)
        expect(self.page.get_by_test_id("workspace-tab-reports")).to_be_visible(timeout=10000)

    def test_patient_selection_keeps_chat_after_todo_sidebar_refresh(self):
        conversation = Conversation.objects.create(
            type=ConversationType.PATIENT_STUDIO,
            patient=self.patient,
            studio=self.studio,
            created_by=self.doctor_user,
        )
        Message.objects.create(
            conversation=conversation,
            sender=self.patient_user,
            sender_role_snapshot=MessageSenderRole.PATIENT,
            sender_display_name_snapshot="Browser Patient",
            studio_name_snapshot=self.studio.name,
            text_content="聊天保持回归测试",
        )

        self.open_doctor_workspace()
        self.page.locator('[data-patient-item][data-patient-id="%s"]' % self.patient.id).click()

        expect(self.page.locator("#patient-content")).to_contain_text("概况", timeout=10000)
        expect(self.page.locator("#patient-todo-list")).to_contain_text("Browser Patient的待办", timeout=10000)
        expect(self.page.locator("#chat-messages-container")).to_contain_text("聊天保持回归测试", timeout=10000)
        expect(self.page.locator('[data-test="empty-state"]')).to_be_hidden(timeout=10000)

    def test_patient_workspace_core_tabs_load(self):
        self.open_patient_workspace()

        self.page.get_by_test_id("workspace-tab-indicators").click()
        expect(self.page.locator("#indicators-wrapper")).to_be_visible(timeout=10000)
        expect(self.page.locator("#patient-content")).to_contain_text("常规监测指标", timeout=10000)

        self.page.get_by_test_id("workspace-tab-statistics").click()
        expect(self.page.locator("#patient-content")).to_contain_text("患者服务包", timeout=10000)
        expect(self.page.locator("#patient-content")).to_contain_text("管理数据概览", timeout=10000)

        self.page.get_by_test_id("workspace-tab-settings").click()
        expect(self.page.locator("#patient-profile-card")).to_be_visible(timeout=10000)
        expect(self.page.locator("#patient-content")).to_contain_text("个人资料", timeout=10000)

        self.page.get_by_test_id("workspace-tab-reports").click()
        expect(self.page.get_by_test_id("reports-history-content")).to_be_visible(timeout=10000)
        expect(self.page.locator("#patient-content")).to_contain_text("诊疗记录", timeout=10000)

    def test_indicators_filter_controls_survive_search_refresh(self):
        today = timezone.localdate()
        selected_cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="浏览器中间疗程",
            start_date=today - timedelta(days=9),
            end_date=today,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        TreatmentCycle.objects.create(
            patient=self.patient,
            name="浏览器后续疗程",
            start_date=today + timedelta(days=1),
            end_date=today + timedelta(days=10),
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )

        self.open_patient_workspace()
        self.page.get_by_test_id("workspace-tab-indicators").click()

        form = self.page.locator("#routine-filter-form")
        start_input = form.locator("#routine_start_date")
        end_input = form.locator("#routine_end_date")
        search_button = form.get_by_role("button", name="搜索")

        expect(start_input).to_be_visible(timeout=10000)
        expect(end_input).to_be_visible(timeout=10000)
        expect(search_button).to_be_visible(timeout=10000)

        start_value = (today - timedelta(days=6)).isoformat()
        end_value = today.isoformat()
        start_input.fill(start_value)
        end_input.fill(end_value)
        with self.page.expect_response(lambda response: "/indicators/" in response.url and "filter_type=date" in response.url):
            search_button.click()

        expect(self.page.locator("#indicators-wrapper")).to_be_visible(timeout=10000)
        form = self.page.locator("#routine-filter-form")
        start_input = form.locator("#routine_start_date")
        end_input = form.locator("#routine_end_date")
        search_button = form.get_by_role("button", name="搜索")
        expect(start_input).to_be_visible(timeout=10000)
        expect(end_input).to_be_visible(timeout=10000)
        expect(search_button).to_be_visible(timeout=10000)
        expect(start_input).to_have_value(start_value)
        expect(end_input).to_have_value(end_value)

        form.locator("[data-routine-filter-type]").select_option("cycle")
        cycle_select = form.locator('select[name="cycle_id"]')
        expect(cycle_select).to_be_visible(timeout=10000)
        cycle_select.select_option(str(selected_cycle.id))
        with self.page.expect_response(
            lambda response: "/indicators/" in response.url
            and "filter_type=cycle" in response.url
            and "cycle_id=%s" % selected_cycle.id in response.url
        ):
            form.get_by_role("button", name="搜索").click()

        expect(self.page.locator("#indicators-wrapper")).to_be_visible(timeout=10000)
        form = self.page.locator("#routine-filter-form")
        cycle_select = form.locator('select[name="cycle_id"]')
        expect(cycle_select).to_be_visible(timeout=10000)
        expect(form.get_by_role("button", name="搜索")).to_be_visible(timeout=10000)
        expect(cycle_select).to_have_value(str(selected_cycle.id))
        expect(self.page.locator("#patient-content")).to_contain_text("浏览器中间疗程", timeout=10000)

    def test_settings_profile_edit_modal_opens_and_closes(self):
        self.open_patient_workspace()
        self.page.get_by_test_id("workspace-tab-settings").click()
        expect(self.page.locator("#patient-profile-card")).to_be_visible(timeout=10000)

        self.page.locator('#patient-profile-card button:has-text("编辑")').click()
        modal = self.page.locator("#edit-profile-modal")
        expect(modal).to_be_visible(timeout=10000)
        expect(modal).to_contain_text("编辑个人资料")

        modal.locator('button[type="button"]').first.click()
        expect(modal).to_be_hidden(timeout=10000)

    def test_settings_history_cycle_detail_opens_in_history_panel_and_closes(self):
        today = timezone.localdate()
        TreatmentCycle.objects.create(
            patient=self.patient,
            name="浏览器当前疗程",
            start_date=today - timedelta(days=2),
            end_date=today + timedelta(days=12),
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        historical_cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="浏览器历史疗程",
            start_date=today - timedelta(days=30),
            end_date=today - timedelta(days=15),
            status=choices.TreatmentCycleStatus.COMPLETED,
        )

        self.open_patient_workspace()
        self.page.get_by_test_id("workspace-tab-settings").click()

        expect(self.page.locator("#plan-table-slot #plan-table-container")).to_be_visible(timeout=10000)
        history_slot = self.page.locator("#history-plan-table-slot")
        self.assertEqual(history_slot.inner_html().strip(), "")

        history_row = self.page.locator(
            '[data-history-cycle-row][data-cycle-id="%s"]' % historical_cycle.id
        )
        expect(history_row).to_be_visible(timeout=10000)
        expect(history_row).to_contain_text("浏览器历史疗程")
        self.assertIn("hover:bg-slate-50", history_row.get_attribute("class") or "")

        with self.page.expect_response(
            lambda response: "/settings/plan-table/" in response.url
            and "cycle_id=%s" % historical_cycle.id in response.url
            and "detail_context=history" in response.url
        ):
            history_row.get_by_text("浏览器历史疗程").click()

        expect(history_slot.locator("[data-history-plan-table-panel]")).to_be_visible(timeout=10000)
        expect(history_slot).to_contain_text("历史疗程配置详情")
        expect(history_slot).to_contain_text("浏览器历史疗程")
        expect(history_slot.locator("#history-plan-table-container")).to_be_visible(timeout=10000)
        expect(self.page.locator("#plan-table-slot #plan-table-container")).to_be_visible(timeout=10000)
        expect(self.page.locator("#history-plan-table-slot #plan-table-container")).to_have_count(0)
        expect(history_row).to_have_attribute("aria-selected", "true")
        self.assertIn("bg-indigo-50", history_row.get_attribute("class") or "")

        history_slot.get_by_role("button", name="关闭配置详情").click()

        expect(history_slot.locator("[data-history-plan-table-panel]")).to_have_count(0)
        self.page.wait_for_function(
            "selector => !document.querySelector(selector).hasAttribute('aria-selected')",
            arg='[data-history-cycle-row][data-cycle-id="%s"]' % historical_cycle.id,
        )
        self.assertEqual(history_slot.inner_html().strip(), "")
        self.assertNotIn("bg-indigo-50", history_row.get_attribute("class") or "")

    def test_change_password_page_loads_and_returns_to_workspace(self):
        self.page.goto(self.url_for("web_doctor:doctor_change_password"), wait_until="domcontentloaded")

        expect(self.page.locator("body")).to_contain_text("医生工作室 · 修改密码")
        expect(self.page.locator('input[name="old_password"]')).to_be_visible()
        expect(self.page.locator('input[name="new_password1"]')).to_be_visible()
        expect(self.page.locator('input[name="new_password2"]')).to_be_visible()

        self.page.get_by_role("link", name="返回工作台").click()
        expect(self.page.locator("#patient-list-container")).to_be_visible(timeout=10000)
