from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from users.models import DoctorProfile


User = get_user_model()


class DoctorWorkspaceSidebarLayoutTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="doc_sidebar_layout",
            password="password",
            user_type=2,
            phone="13900139002",
        )
        DoctorProfile.objects.create(user=self.user, name="Dr. Sidebar")
        self.client.force_login(self.user)

    @patch("web_doctor.views.workspace.enrich_patients_with_counts", return_value=[])
    def test_workspace_contains_collapsible_patient_sidebar_contract(self, _mock_enrich):
        response = self.client.get(reverse("web_doctor:doctor_workspace"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="doctor-patient-sidebar"', html=False)
        self.assertContains(response, 'data-collapsed="false"', html=False)
        self.assertContains(response, 'id="doctor-patient-sidebar-content"', html=False)
        self.assertContains(response, 'id="doctor-patient-sidebar-toggle"', html=False)
        self.assertContains(
            response,
            'aria-controls="doctor-patient-sidebar-content"',
            html=False,
        )
        self.assertContains(response, 'aria-expanded="true"', html=False)
        self.assertContains(response, 'aria-label="收起患者菜单"', html=False)
        self.assertContains(
            response,
            'web_doctor/doctor_workspace_sidebar.js',
            html=False,
        )
