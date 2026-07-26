import os
from urllib.parse import urljoin

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse

os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import expect, sync_playwright
except ModuleNotFoundError:
    PlaywrightError = Exception
    expect = None
    sync_playwright = None


class LoginPagesBrowserTests(StaticLiveServerTestCase):
    desktop_viewport = {"width": 1440, "height": 900}
    mobile_viewport = {"width": 390, "height": 844}

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if sync_playwright is None:
            raise RuntimeError(
                "Python Playwright is not installed. Run: pip install -r requirements.txt"
            )

        headless = os.getenv("PLAYWRIGHT_HEADLESS", "1").lower() not in {
            "0",
            "false",
            "no",
        }
        cls._playwright = sync_playwright().start()
        try:
            cls.browser = cls._playwright.chromium.launch(headless=headless)
        except PlaywrightError as exc:
            cls._playwright.stop()
            raise RuntimeError(
                "Playwright Chromium is not installed. "
                "Run: python -m playwright install chromium"
            ) from exc

    @classmethod
    def tearDownClass(cls):
        try:
            if getattr(cls, "browser", None):
                cls.browser.close()
        finally:
            if getattr(cls, "_playwright", None):
                cls._playwright.stop()
            super().tearDownClass()

    def setUp(self):
        self.context = None
        self.page = None
        self._use_viewport(self.desktop_viewport)

    def tearDown(self):
        if self.context:
            self.context.close()

    def _use_viewport(self, viewport):
        if self.context:
            self.context.close()
        self.context = self.browser.new_context(
            base_url=self.live_server_url,
            reduced_motion="reduce",
            viewport=viewport,
        )
        self.page = self.context.new_page()

    def _url_for(self, view_name):
        return urljoin(self.live_server_url, reverse(view_name))

    def _open(self, url):
        self.page.goto(url, wait_until="networkidle")

    def _assert_no_horizontal_overflow(self):
        metrics = self.page.evaluate(
            """() => ({
                clientWidth: document.documentElement.clientWidth,
                scrollWidth: document.documentElement.scrollWidth,
            })"""
        )
        self.assertLessEqual(
            metrics["scrollWidth"],
            metrics["clientWidth"] + 1,
            metrics,
        )

    def _assert_element_fits_viewport_width(self, selector):
        bounds = self.page.locator(selector).evaluate(
            """element => {
                const rect = element.getBoundingClientRect();
                return {
                    left: rect.left,
                    right: rect.right,
                    viewportWidth: window.innerWidth,
                };
            }"""
        )
        self.assertGreaterEqual(bounds["left"], -1, bounds)
        self.assertLessEqual(bounds["right"], bounds["viewportWidth"] + 1, bounds)

    def _assert_grid_column_count(self, selector, expected_count):
        columns = self.page.locator(selector).evaluate(
            "element => getComputedStyle(element).gridTemplateColumns"
        )
        self.assertEqual(len(columns.split()), expected_count, columns)

    def test_staff_login_desktop_renders_new_layout_and_client_validation(self):
        self._open(self._url_for("web_doctor:login"))

        expect(self.page.locator(".portal-login-brand-tag")).to_have_text(
            "ZenCare Digital Health"
        )
        expect(self.page.locator(".portal-login-trust-group .trust-chip")).to_have_count(
            3
        )
        expect(self.page.locator("#portal-login-form")).to_be_visible()
        expect(self.page.locator('input[name="phone"]')).to_be_visible()
        expect(self.page.locator('input[name="password"]')).to_be_visible()
        expect(
            self.page.get_by_role("button", name="使用手机号登录")
        ).to_be_visible()
        self._assert_grid_column_count(".portal-login-page", 2)
        self._assert_no_horizontal_overflow()

        self.page.get_by_role("button", name="使用手机号登录").click()

        expect(self.page.locator("#login-client-errors")).to_be_visible()
        expect(self.page.locator("#login-client-errors")).to_contain_text(
            "请输入手机号"
        )
        expect(self.page.locator("#login-client-errors")).to_contain_text(
            "请输入密码"
        )
        expect(self.page.locator("#login-phone")).to_be_focused()

    def test_staff_login_mobile_reflows_without_horizontal_overflow(self):
        self._use_viewport(self.mobile_viewport)
        self._open(self._url_for("web_doctor:login"))

        self._assert_grid_column_count(".portal-login-page", 1)
        expect(self.page.locator(".portal-login-brand-copy")).to_be_hidden()
        expect(self.page.locator(".portal-login-trust-group")).to_be_hidden()
        expect(self.page.locator("#portal-login-form")).to_be_visible()
        self._assert_element_fits_viewport_width(".portal-login-form-wrap")
        self._assert_no_horizontal_overflow()

    def test_admin_login_desktop_preserves_form_contract_and_new_layout(self):
        admin_index_url = reverse("admin:index")
        admin_login_url = f"{self._url_for('admin:login')}?next={admin_index_url}"
        self._open(admin_login_url)

        expect(self.page.locator(".admin-login-brand-tag")).to_have_text(
            "ZenCare Digital Health"
        )
        expect(self.page.locator(".admin-login-trust-group .trust-chip")).to_have_count(
            3
        )
        expect(self.page.locator("#login-form")).to_be_visible()
        expect(self.page.locator('input[name="username"]')).to_be_visible()
        expect(self.page.locator('input[name="password"]')).to_be_visible()
        expect(self.page.locator('input[name="next"]')).to_have_value(admin_index_url)
        expect(self.page.get_by_role("button", name="进入管理后台")).to_be_visible()
        expect(self.page.locator(".portal-login-footer")).to_contain_text(
            "上海智医康科技有限公司"
        )
        self._assert_grid_column_count(".admin-login-shell", 2)
        self._assert_no_horizontal_overflow()

    def test_admin_login_mobile_reflows_without_horizontal_overflow(self):
        self._use_viewport(self.mobile_viewport)
        self._open(self._url_for("admin:login"))

        self._assert_grid_column_count(".admin-login-shell", 1)
        expect(self.page.locator("#login-form")).to_be_visible()
        expect(self.page.get_by_role("button", name="进入管理后台")).to_be_visible()
        self._assert_element_fits_viewport_width(".admin-login-form-wrap")
        self._assert_no_horizontal_overflow()
