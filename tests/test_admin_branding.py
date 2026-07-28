from django.templatetags.static import static
from django.test import SimpleTestCase
from django.urls import reverse


class AdminBrandingTests(SimpleTestCase):
    def test_admin_login_references_browser_favicon(self):
        response = self.client.get(reverse("admin:login"))

        self.assertContains(
            response,
            (
                '<link rel="icon" type="image/png" sizes="32x32" '
                f'href="{static("icon32.png")}">'
            ),
            html=True,
        )

    def test_admin_login_uses_approved_healthcare_branding(self):
        response = self.client.get(
            reverse("admin:login"),
            {"next": reverse("admin:index")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "admin/login.html")
        self.assertContains(response, static("logo-192.png"))
        self.assertEqual(
            response.content.decode().count(static("logo-192.png")),
            1,
        )
        self.assertNotContains(
            response,
            "仅限已授权的医务及运营管理人员使用",
        )
        self.assertContains(response, "基于AI与智能硬件的")
        self.assertContains(response, "慢病数字化康复管理")
        self.assertContains(
            response,
            (
                "连接患者与医生的数字化桥梁。通过医疗级物联网硬件实现连续体征监测，"
                "将院外康复由“盲盒”状态转为精细化管理。"
            ),
        )
        self.assertContains(response, 'id="login-form"')
        self.assertContains(response, 'name="username"')
        self.assertContains(response, 'name="password"')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertContains(
            response,
            f'<input type="hidden" name="next" value="{reverse("admin:index")}">',
            html=True,
        )
        self.assertContains(response, 'type="submit"')
