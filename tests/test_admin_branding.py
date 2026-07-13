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
