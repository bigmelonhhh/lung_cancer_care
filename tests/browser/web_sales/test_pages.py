from django.test import tag
from django.urls import reverse

from tests.browser.web_sales.base import (
    SalesBrowserTestCase,
    SalesMobileBrowserTestCase,
    expect,
)


@tag("browser")
class SalesPagesBrowserTests(SalesBrowserTestCase):
    def test_dashboard_lists_doctors_patients_and_loads_detail_cards(self):
        self.open_sales_dashboard()

        expect(self.page.locator("body")).to_contain_text("你好，Browser Sales")
        expect(self.page.locator("body")).to_contain_text("管理医生总数")
        expect(self.page.locator("body")).to_contain_text("管理患者总数")
        expect(self.page.locator("body")).to_contain_text("Browser Doctor")
        expect(self.page.locator("body")).to_contain_text("Browser Doctor Two")
        expect(self.page.locator("body")).to_contain_text("Browser Patient")

        self.page.locator(
            f'[hx-get="{reverse("web_sales:doctor_detail", args=[self.doctor.id])}"]'
        ).click()
        expect(self.page.locator("#main-content-area")).to_contain_text("医生档案", timeout=10000)
        expect(self.page.locator("#main-content-area")).to_contain_text("Browser Doctor")
        expect(self.page.locator("#main-content-area")).to_contain_text("Browser Hospital")
        expect(self.page.get_by_role("button", name="返回到首页")).to_be_visible()

        self.page.get_by_role("button", name="返回到首页").click()
        expect(self.page.locator("#main-content-area")).to_contain_text("管理医生总数", timeout=10000)

        self.page.locator(
            f'[hx-get="{reverse("web_sales:patient_detail", args=[self.patient.id])}"]'
        ).click()
        expect(self.page.locator("#main-content-area")).to_contain_text("基础信息", timeout=10000)
        expect(self.page.locator("#main-content-area")).to_contain_text("Browser Patient")
        expect(self.page.locator("#main-content-area")).to_contain_text("13900002000")
        expect(self.page.locator("#main-content-area")).to_contain_text("绑定二维码")
        expect(self.page.locator('select[name="doctor_id"]')).to_be_visible()

    def test_patient_detail_doctor_select_updates_with_htmx(self):
        self.open_sales_dashboard()
        self.page.locator(
            f'[hx-get="{reverse("web_sales:patient_detail", args=[self.patient.id])}"]'
        ).click()
        expect(self.page.locator("#main-content-area")).to_contain_text("基础信息", timeout=10000)

        self.page.locator('select[name="doctor_id"]').select_option(str(self.second_doctor.id))

        expect(self.page.locator("#doctor-update-toast")).to_contain_text(
            "已保存：Browser Doctor Two",
            timeout=10000,
        )

    def test_dashboard_htmx_partial_loads_without_full_shell(self):
        self.context.set_extra_http_headers({"HX-Request": "true"})
        self.page.goto(self.url_for("web_sales:sales_dashboard"), wait_until="domcontentloaded")

        expect(self.page.locator("body")).to_contain_text("你好，Browser Sales")
        expect(self.page.locator("body")).to_contain_text("管理医生总数")
        expect(self.page.locator("body")).not_to_contain_text("我的医生")
        expect(self.page.locator("[data-ws-card]")).to_be_visible()

    def test_change_password_page_loads_and_returns_to_dashboard(self):
        self.page.goto(
            self.url_for("web_sales:sales_change_password"),
            wait_until="domcontentloaded",
        )

        expect(self.page.locator("body")).to_contain_text("销售工作台 · 修改密码")
        expect(self.page.locator("body")).to_contain_text("更新登录密码")
        expect(self.page.locator('input[name="old_password"]')).to_be_visible()
        expect(self.page.locator('input[name="new_password1"]')).to_be_visible()
        expect(self.page.locator('input[name="new_password2"]')).to_be_visible()

        self.page.get_by_role("link", name="返回工作台").click()
        expect(self.page.locator("body")).to_contain_text("你好，Browser Sales", timeout=10000)


@tag("browser")
class SalesMobilePagesBrowserTests(SalesMobileBrowserTestCase):
    def test_mobile_dashboard_cookie_renders_mobile_template_and_sidebar(self):
        self.context.add_cookies(
            [
                {
                    "name": "ws_is_mobile",
                    "value": "1",
                    "url": self.live_server_url,
                    "sameSite": "Lax",
                }
            ]
        )
        self.open_sales_dashboard()

        expect(self.page.locator("[data-ws-sidebar]")).to_be_visible()
        expect(self.page.locator("#main-content-area[data-ws-safe-bottom]")).to_be_visible()
        expect(self.page.locator("body")).to_contain_text("我的医生")
        expect(self.page.locator("body")).to_contain_text("我的患者")
        expect(self.page.locator("body")).to_contain_text("Browser Patient")

        self.page.get_by_label("打开导航").click()
        expect(self.page.locator("[data-ws-sidebar]")).to_be_visible()
