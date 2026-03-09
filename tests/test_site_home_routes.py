from django.test import SimpleTestCase
from django.urls import reverse


class SiteHomeRouteTests(SimpleTestCase):
    def test_root_path_renders_static_homepage(self):
        response = self.client.get(reverse("site_home"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "index.html")

    def test_index_html_path_renders_static_homepage(self):
        response = self.client.get(reverse("site_home_index"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "index.html")

    def test_homepage_contains_core_ui_elements(self):
        response = self.client.get(reverse("site_home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "智医康 - 基于AI与智能硬件的肺癌数字化康复管理")
        self.assertContains(response, '<meta name="viewport" content="width=device-width, initial-scale=1.0">')
        self.assertContains(response, 'href="#home"')
        self.assertContains(response, 'href="#carrier"')
        self.assertContains(response, 'href="#dtx"')
        self.assertContains(response, 'href="#about"')
        self.assertContains(response, "了解详情")
