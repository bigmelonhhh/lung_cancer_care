from django.test import tag

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

    def test_change_password_page_loads_and_returns_to_workspace(self):
        self.page.goto(self.url_for("web_doctor:doctor_change_password"), wait_until="domcontentloaded")

        expect(self.page.locator("body")).to_contain_text("医生工作室 · 修改密码")
        expect(self.page.locator('input[name="old_password"]')).to_be_visible()
        expect(self.page.locator('input[name="new_password1"]')).to_be_visible()
        expect(self.page.locator('input[name="new_password2"]')).to_be_visible()

        self.page.get_by_role("link", name="返回工作台").click()
        expect(self.page.locator("#patient-list-container")).to_be_visible(timeout=10000)
