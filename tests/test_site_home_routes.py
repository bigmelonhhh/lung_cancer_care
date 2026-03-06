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
