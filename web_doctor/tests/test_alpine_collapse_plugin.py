from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from unittest.mock import patch

from users.models import DoctorProfile

User = get_user_model()


class AlpineCollapsePluginTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="doc_alpine_collapse",
            password="password",
            user_type=2,
            phone="13900139002",
        )
        DoctorProfile.objects.create(user=self.user, name="Dr. Alpine")

    @patch("web_doctor.views.workspace.enrich_patients_with_counts", return_value=[])
    def test_doctor_pages_load_collapse_plugin_before_alpine_core(self, _mock_enrich):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("web_doctor:doctor_workspace"))
        self.assertEqual(resp.status_code, 200)

        html = resp.content.decode("utf-8")
        collapse_idx = html.find("@alpinejs/collapse")
        core_idx = html.find("unpkg.com/alpinejs")
        self.assertNotEqual(collapse_idx, -1)
        self.assertNotEqual(core_idx, -1)
        self.assertLess(collapse_idx, core_idx)

