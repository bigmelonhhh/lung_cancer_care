from django.test import tag

from tests.browser.web_doctor.base import DoctorBrowserTestCase, expect


STORAGE_KEY = "lcc:doctor-workspace:left-sidebar-collapsed:v1"


@tag("browser")
class DoctorWorkspaceSidebarBrowserTests(DoctorBrowserTestCase):
    def _open_with_default_sidebar_state(self):
        self.page.add_init_script(
            """
            if (!window.sessionStorage.getItem("__sidebar_test_storage_reset")) {
                window.localStorage.removeItem(%s);
                window.sessionStorage.setItem("__sidebar_test_storage_reset", "1");
            }
            """
            % repr(STORAGE_KEY)
        )
        self.open_doctor_workspace()

    def test_sidebar_toggle_reflows_workspace_and_notifies_layout_listeners(self):
        self._open_with_default_sidebar_state()

        sidebar = self.page.locator("#doctor-patient-sidebar")
        content = self.page.locator("#doctor-patient-sidebar-content")
        toggle = self.page.locator("#doctor-patient-sidebar-toggle")
        collapse_icon = toggle.locator("[data-sidebar-collapse-icon]")
        expand_icon = toggle.locator("[data-sidebar-expand-icon]")
        main = self.page.locator("#main-content")
        right_sidebar = self.page.locator("aside").nth(1)

        expect(sidebar).to_have_attribute("data-collapsed", "false")
        expect(sidebar).to_have_css("width", "288px")
        expect(content).to_be_visible()
        expect(toggle).to_have_attribute("aria-expanded", "true")
        expect(collapse_icon).to_be_visible()
        expect(expand_icon).to_be_hidden()

        initial_main_width = main.bounding_box()["width"]
        initial_right_width = right_sidebar.bounding_box()["width"]
        self.page.evaluate(
            """
            window.__doctorSidebarResizeEvents = 0;
            window.addEventListener("resize", function () {
                window.__doctorSidebarResizeEvents += 1;
            });
            """
        )

        toggle.click()

        expect(sidebar).to_have_attribute("data-collapsed", "true")
        expect(sidebar).to_have_css("width", "56px")
        expect(content).to_be_hidden()
        expect(toggle).to_have_attribute("aria-expanded", "false")
        expect(toggle).to_have_attribute("aria-label", "展开患者菜单")
        expect(collapse_icon).to_be_hidden()
        expect(expand_icon).to_be_visible()
        self.page.wait_for_function("window.__doctorSidebarResizeEvents > 0")

        collapsed_main_width = main.bounding_box()["width"]
        collapsed_right_width = right_sidebar.bounding_box()["width"]
        self.assertAlmostEqual(collapsed_main_width - initial_main_width, 232, delta=1)
        self.assertAlmostEqual(collapsed_right_width, initial_right_width, delta=1)

    def test_sidebar_state_persists_and_toggle_supports_keyboard(self):
        self._open_with_default_sidebar_state()

        sidebar = self.page.locator("#doctor-patient-sidebar")
        content = self.page.locator("#doctor-patient-sidebar-content")
        toggle = self.page.locator("#doctor-patient-sidebar-toggle")

        toggle.focus()
        self.page.keyboard.press("Enter")
        expect(sidebar).to_have_attribute("data-collapsed", "true")
        expect(content).to_be_hidden()
        self.assertEqual(
            self.page.evaluate("window.localStorage.getItem(%s)" % repr(STORAGE_KEY)),
            "1",
        )

        self.page.reload(wait_until="domcontentloaded")
        expect(sidebar).to_have_attribute("data-collapsed", "true")
        expect(sidebar).to_have_css("width", "56px")
        expect(content).to_be_hidden()

        toggle.focus()
        self.page.keyboard.press("Enter")
        expect(sidebar).to_have_attribute("data-collapsed", "false")
        expect(sidebar).to_have_css("width", "288px")
        expect(content).to_be_visible()
        expect(toggle).to_have_attribute("aria-expanded", "true")
        expect(toggle).to_have_attribute("aria-label", "收起患者菜单")
        self.assertEqual(
            self.page.evaluate("window.localStorage.getItem(%s)" % repr(STORAGE_KEY)),
            "0",
        )

    def test_sidebar_toggle_keeps_loaded_patient_workspace(self):
        self.open_patient_workspace()

        patient_content = self.page.locator("#patient-content")
        toggle = self.page.locator("#doctor-patient-sidebar-toggle")
        expect(patient_content).to_contain_text("概况", timeout=10000)
        expect(self.page.locator('[data-test="empty-state"]')).to_be_hidden(timeout=10000)
        self.page.evaluate(
            """
            window.__doctorSidebarHtmxRequests = 0;
            document.body.addEventListener("htmx:beforeRequest", function () {
                window.__doctorSidebarHtmxRequests += 1;
            });
            """
        )

        toggle.click()

        expect(self.page.locator("#doctor-patient-sidebar")).to_have_attribute(
            "data-collapsed", "true"
        )
        expect(patient_content).to_contain_text("概况")
        expect(self.page.locator('[data-test="empty-state"]')).to_be_hidden()
        self.assertEqual(self.page.evaluate("window.__doctorSidebarHtmxRequests"), 0)
