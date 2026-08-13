from datetime import timedelta

from django.test import tag
from django.utils import timezone

from chat.models import Conversation, ConversationType, Message, MessageSenderRole
from core.models import (
    CheckupFieldMapping,
    CheckupLibrary,
    Questionnaire,
    StandardField,
    StandardFieldValueType,
    TreatmentCycle,
    choices,
)
from tests.browser.web_doctor.base import DoctorBrowserTestCase, expect


@tag("browser")
class DoctorCorePagesBrowserTests(DoctorBrowserTestCase):
    def _create_followup_review_mapping(self):
        checkup = CheckupLibrary.objects.create(
            name="浏览器复查血常规",
            code="BROWSER_FOLLOWUP_REVIEW",
            category=choices.CheckupCategory.BLOOD,
            is_active=True,
        )
        field = StandardField.objects.create(
            local_code="BROWSER_REVIEW_WBC",
            chinese_name="浏览器白细胞",
            english_abbr="WBC",
            value_type=StandardFieldValueType.DECIMAL,
            is_active=True,
        )
        return CheckupFieldMapping.objects.create(
            checkup_item=checkup,
            standard_field=field,
            is_active=True,
        )

    def _open_followup_review_config_modal(self):
        self.page.locator("#followup-review-section").get_by_role("button", name="配置").click()
        modal = self.page.locator('[data-followup-review-modal-layer]:visible')
        expect(modal).to_have_count(1, timeout=10000)
        expect(modal.first).to_contain_text("配置核心关注指标")
        return modal.first

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
            text_content="短讯",
        )

        self.open_doctor_workspace()
        self.page.locator('[data-patient-item][data-patient-id="%s"]' % self.patient.id).click()

        expect(self.page.locator("#patient-content")).to_contain_text("概况", timeout=10000)
        expect(self.page.locator("#patient-todo-list")).to_contain_text("Browser Patient的待办", timeout=10000)
        messages = self.page.locator("#chat-messages-container")
        expect(messages).to_contain_text("短讯", timeout=10000)
        expect(self.page.locator('[data-test="empty-state"]')).to_be_hidden(timeout=10000)

        bubble = messages.locator('[data-test="message-bubble"]').filter(has_text="短讯")
        expect(bubble).to_have_css("min-width", "72px")
        expect(bubble).to_have_css("display", "flex")
        expect(bubble).to_have_css("align-items", "center")
        expect(bubble).to_have_css("justify-content", "center")
        expect(bubble.locator("p")).to_have_css("text-align", "start")

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

    def test_followup_review_config_modal_reopens_after_cancel_and_save(self):
        self._create_followup_review_mapping()

        self.open_patient_workspace()
        self.page.get_by_test_id("workspace-tab-indicators").click()
        expect(self.page.locator("#followup-review-section")).to_be_visible(timeout=10000)

        modal = self._open_followup_review_config_modal()
        modal.get_by_text("浏览器白细胞").first.click()
        modal.get_by_role("button", name="取消").click()
        expect(self.page.locator('[data-followup-review-modal-layer]:visible')).to_have_count(0, timeout=10000)

        modal = self._open_followup_review_config_modal()
        modal.get_by_text("浏览器白细胞").first.click()
        with self.page.expect_response(lambda response: "/indicators/preferences/" in response.url):
            modal.get_by_role("button", name="确定").click()
        expect(self.page.locator("#followup-review-section")).to_be_visible(timeout=10000)
        expect(self.page.locator('[data-followup-review-modal-layer]:visible')).to_have_count(0, timeout=10000)

        self._open_followup_review_config_modal()

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

    def test_settings_plan_searches_filter_independently_and_survive_htmx_updates(self):
        today = timezone.localdate()
        current_cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="浏览器搜索当前疗程",
            start_date=today - timedelta(days=2),
            end_date=today + timedelta(days=18),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        future_cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="浏览器搜索未来疗程",
            start_date=today + timedelta(days=30),
            end_date=today + timedelta(days=50),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        CheckupLibrary.objects.create(
            name="浏览器胸部增强CT",
            code="BROWSER_SEARCH_CHEST_CT",
            category=choices.CheckupCategory.IMAGING,
            is_active=True,
        )
        CheckupLibrary.objects.create(
            name="浏览器血液肿瘤标志物",
            code="BROWSER_SEARCH_BLOOD_MARKER",
            category=choices.CheckupCategory.BLOOD,
            is_active=True,
        )
        Questionnaire.objects.create(
            name="浏览器睡眠质量量表",
            code="Q_BROWSER_SEARCH_SLEEP",
            is_active=True,
        )
        Questionnaire.objects.create(
            name="浏览器呼吸困难量表",
            code="Q_BROWSER_SEARCH_BREATH",
            is_active=True,
        )

        self.open_patient_workspace()
        self.page.get_by_test_id("workspace-tab-settings").click()

        plan_container = self.page.locator("#plan-table-slot #plan-table-container")
        expect(plan_container).to_be_visible(timeout=10000)
        expect(self.page.locator('[data-cycle-select-row][data-cycle-id="%s"]' % current_cycle.id)).to_have_attribute(
            "aria-current", "true"
        )

        checkup_search = plan_container.get_by_label("搜索复查类目")
        questionnaire_search = plan_container.get_by_label("搜索量表")
        chest_row = plan_container.locator('[data-plan-filter-text="浏览器胸部增强CT"]')
        blood_row = plan_container.locator('[data-plan-filter-text="浏览器血液肿瘤标志物"]')
        sleep_row = plan_container.locator('[data-plan-filter-text="浏览器睡眠质量量表"]')
        breath_row = plan_container.locator('[data-plan-filter-text="浏览器呼吸困难量表"]')

        checkup_search.fill("胸部增强")
        expect(chest_row).to_be_visible()
        expect(blood_row).to_be_hidden()
        expect(sleep_row).to_be_visible()
        expect(breath_row).to_be_visible()

        questionnaire_search.fill("睡眠质量")
        expect(sleep_row).to_be_visible()
        expect(breath_row).to_be_hidden()
        expect(chest_row).to_be_visible()

        checkup_search.fill("不存在的复查")
        expect(plan_container.get_by_text("未找到匹配的复查类目", exact=True)).to_be_visible()
        checkup_search.fill("")
        expect(chest_row).to_be_visible()
        expect(blood_row).to_be_visible()

        checkup_search.fill("胸部增强")
        with self.page.expect_response(lambda response: "/plan-toggle/" in response.url):
            chest_row.locator("[data-checkup-toggle]").check(force=True)
        expect(chest_row).to_be_visible(timeout=10000)
        expect(checkup_search).to_have_value("胸部增强")

        with self.page.expect_response(
            lambda response: "/settings/" in response.url and "cycle_id=%s" % future_cycle.id in response.url
        ):
            self.page.locator('[data-cycle-select-row][data-cycle-id="%s"]' % future_cycle.id).click()
        plan_container = self.page.locator("#plan-table-slot #plan-table-container")
        expect(plan_container).to_be_visible(timeout=10000)
        refreshed_search = plan_container.get_by_label("搜索复查类目")
        refreshed_search.fill("血液肿瘤")
        expect(plan_container.locator('[data-plan-filter-text="浏览器血液肿瘤标志物"]')).to_be_visible()
        expect(plan_container.locator('[data-plan-filter-text="浏览器胸部增强CT"]')).to_be_hidden()

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
        expect(history_slot.locator("[data-plan-filter-input]")).to_have_count(0)
        expect(self.page.locator("#plan-table-slot #plan-table-container")).to_be_visible(timeout=10000)
        expect(self.page.locator("#history-plan-table-slot #plan-table-container")).to_have_count(0)
        expect(history_row).to_have_attribute("aria-selected", "true")
        self.assertIn("bg-indigo-50", history_row.get_attribute("class") or "")
        detached_history_head = history_slot.locator(
            "[data-plan-table-head]"
        ).element_handle()
        self.assertIsNotNone(detached_history_head)

        history_slot.get_by_role("button", name="关闭配置详情").click()

        expect(history_slot.locator("[data-history-plan-table-panel]")).to_have_count(0)
        self.page.wait_for_function(
            "selector => !document.querySelector(selector).hasAttribute('aria-selected')",
            arg='[data-history-cycle-row][data-cycle-id="%s"]' % historical_cycle.id,
        )
        self.assertEqual(history_slot.inner_html().strip(), "")
        self.assertNotIn("bg-indigo-50", history_row.get_attribute("class") or "")
        width_after_close = detached_history_head.evaluate(
            """
            node => {
              node.style.width = '';
              window.dispatchEvent(new Event('resize'));
              const container = node.closest('[data-plan-table-container]');
              return {
                width: node.style.width,
                hasCleanup: typeof container.__cleanupPlanTableStickyHead === 'function'
              };
            }
            """
        )
        self.assertEqual(width_after_close["width"], "")
        self.assertFalse(width_after_close["hasCleanup"])

    def test_settings_plan_table_keeps_left_header_fixed_while_date_header_syncs(self):
        today = timezone.localdate()
        TreatmentCycle.objects.create(
            patient=self.patient,
            name="浏览器固定列疗程",
            start_date=today - timedelta(days=3),
            end_date=today + timedelta(days=17),
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )

        self.open_patient_workspace()
        self.page.get_by_test_id("workspace-tab-settings").click()

        plan_container = self.page.locator("#plan-table-slot #plan-table-container")
        expect(plan_container).to_be_visible(timeout=10000)
        expect(plan_container.locator("[data-plan-sticky-head-col]")).to_have_count(3)
        expect(plan_container.locator("[data-plan-sticky-section]")).to_have_count(4)

        left_header = plan_container.locator("[data-plan-sticky-head-col]").first
        body_scroll = plan_container.locator("[data-plan-table-body-scroll]")
        date_head = plan_container.locator("[data-plan-table-head]")

        scroll_metrics = body_scroll.evaluate(
            "node => ({ scrollWidth: node.scrollWidth, clientWidth: node.clientWidth })"
        )
        self.assertGreater(scroll_metrics["scrollWidth"], scroll_metrics["clientWidth"])

        scroll_offset = min(scroll_metrics["scrollWidth"] - scroll_metrics["clientWidth"], 240)
        before_box = left_header.bounding_box()
        self.assertIsNotNone(before_box)

        body_scroll.evaluate(
            "(node, value) => { node.scrollLeft = value; node.dispatchEvent(new Event('scroll')); return node.scrollLeft; }",
            scroll_offset,
        )
        self.page.wait_for_timeout(100)

        after_box = left_header.bounding_box()
        self.assertIsNotNone(after_box)
        self.assertLess(abs(after_box["x"] - before_box["x"]), 3)
        self.assertIn(
            f"translateX(-{scroll_offset}px)",
            date_head.evaluate("node => node.style.transform"),
        )

    def test_settings_plan_table_aligns_fixed_and_date_columns_for_supported_cycle_lengths(self):
        self.page.set_viewport_size({"width": 1920, "height": 1080})
        today = timezone.localdate()
        cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="浏览器周期列对齐疗程",
            start_date=today,
            end_date=today + timedelta(days=1),
            cycle_days=2,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        CheckupLibrary.objects.create(
            name="浏览器周期列对齐复查",
            code="BROWSER_PLAN_COLUMN_ALIGNMENT",
            category=choices.CheckupCategory.IMAGING,
            is_active=True,
        )

        for cycle_days in (2, 21, 28, 100):
            with self.subTest(cycle_days=cycle_days):
                cycle.cycle_days = cycle_days
                cycle.end_date = today + timedelta(days=cycle_days - 1)
                cycle.save(update_fields=["cycle_days", "end_date"])

                self.open_patient_workspace()
                self.page.get_by_test_id("workspace-tab-settings").click()

                plan_container = self.page.locator("#plan-table-slot #plan-table-container")
                expect(plan_container).to_be_visible(timeout=10000)
                header_cells = plan_container.locator("[data-plan-sticky-head-col]")
                plan_row = plan_container.locator(
                    '[data-plan-filter-text="浏览器周期列对齐复查"]'
                )
                expect(plan_row).to_be_visible(timeout=10000)
                body_cells = plan_row.locator("[data-plan-sticky-col]")

                for column_index, expected_width in enumerate((192, 96, 96)):
                    header_box = header_cells.nth(column_index).bounding_box()
                    body_box = body_cells.nth(column_index).bounding_box()
                    self.assertIsNotNone(header_box)
                    self.assertIsNotNone(body_box)
                    self.assertAlmostEqual(header_box["x"], body_box["x"], delta=1)
                    self.assertAlmostEqual(header_box["width"], expected_width, delta=1)
                    self.assertAlmostEqual(body_box["width"], expected_width, delta=1)

                day_indexes = sorted({1, min(8, cycle_days), cycle_days})
                for day_index in day_indexes:
                    header_day = plan_container.locator(
                        f'[data-plan-table-head] [data-plan-day="{day_index}"]'
                    )
                    body_day = plan_row.locator("td").nth(day_index + 2)
                    header_box = header_day.bounding_box()
                    body_box = body_day.bounding_box()
                    self.assertIsNotNone(header_box)
                    self.assertIsNotNone(body_box)
                    self.assertAlmostEqual(header_box["x"], body_box["x"], delta=2)
                    self.assertAlmostEqual(header_box["width"], body_box["width"], delta=1)
                    self.assertGreaterEqual(body_box["width"], 31.9)
                    self.assertLessEqual(body_box["width"], 40.2)

                scroll_metrics = plan_container.locator("[data-plan-table-body-scroll]").evaluate(
                    "node => ({ scrollWidth: node.scrollWidth, clientWidth: node.clientWidth })"
                )
                if cycle_days <= 21:
                    self.assertEqual(scroll_metrics["scrollWidth"], scroll_metrics["clientWidth"])
                else:
                    self.assertGreater(scroll_metrics["scrollWidth"], scroll_metrics["clientWidth"])

    def test_settings_plan_table_removes_resize_listener_before_htmx_cleanup(self):
        today = timezone.localdate()
        TreatmentCycle.objects.create(
            patient=self.patient,
            name="浏览器计划表清理疗程",
            start_date=today,
            end_date=today + timedelta(days=20),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )

        self.open_patient_workspace()
        self.page.get_by_test_id("workspace-tab-settings").click()

        plan_container = self.page.locator("#plan-table-slot #plan-table-container")
        expect(plan_container).to_be_visible(timeout=10000)

        width_after_cleanup = plan_container.evaluate(
            """
            node => {
              const headTable = node.querySelector('[data-plan-table-head]');
              node.dispatchEvent(new CustomEvent('htmx:beforeCleanupElement', {
                bubbles: true,
                detail: { elt: node }
              }));
              headTable.style.width = '';
              window.dispatchEvent(new Event('resize'));
              return headTable.style.width;
            }
            """
        )

        self.assertEqual(width_after_cleanup, "")

    def test_change_password_page_loads_and_returns_to_workspace(self):
        self.page.goto(self.url_for("web_doctor:doctor_change_password"), wait_until="domcontentloaded")

        expect(self.page.locator("body")).to_contain_text("医生工作室 · 修改密码")
        expect(self.page.locator('input[name="old_password"]')).to_be_visible()
        expect(self.page.locator('input[name="new_password1"]')).to_be_visible()
        expect(self.page.locator('input[name="new_password2"]')).to_be_visible()

        self.page.get_by_role("link", name="返回工作台").click()
        expect(self.page.locator("#patient-list-container")).to_be_visible(timeout=10000)
