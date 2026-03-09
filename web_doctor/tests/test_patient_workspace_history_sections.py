from unittest.mock import patch

from django.core.paginator import Paginator
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from users.models import DoctorProfile, PatientProfile

User = get_user_model()


class PatientWorkspaceHistorySectionsTests(TestCase):
    def setUp(self):
        self.doctor_user = User.objects.create_user(
            username="doc_workspace_history_sections",
            password="password",
            user_type=2,
            phone="13900139081",
        )
        self.doctor_profile = DoctorProfile.objects.create(
            user=self.doctor_user,
            name="Dr. History",
        )
        self.doctor_user.doctor_profile = self.doctor_profile
        self.doctor_user.save()

        self.patient = PatientProfile.objects.create(
            name="患者历史页",
            phone="13800138281",
            doctor=self.doctor_profile,
        )
        self.client.force_login(self.doctor_user)

    def test_medical_history_section_contains_core_ui_elements(self):
        url = reverse(
            "web_doctor:patient_workspace_section",
            args=[self.patient.id, "medical_history"],
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "web_doctor/partials/medical_history/list.html")
        self.assertContains(response, "病情历史记录")
        self.assertContains(response, "返回")
        self.assertContains(response, 'hx-swap-oob="true"')

    def test_medication_history_section_contains_core_ui_elements(self):
        url = reverse(
            "web_doctor:patient_workspace_section",
            args=[self.patient.id, "medication_history"],
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "web_doctor/partials/medication_history/list.html")
        self.assertContains(response, "历史用药方案")
        self.assertContains(response, "暂无用药数据")

    @patch("web_doctor.views.home.handle_checkup_history_section")
    def test_checkup_history_section_contains_core_ui_elements(self, mock_handler):
        def _fake_handler(_request, context):
            context.update(
                {
                    "history_page": Paginator([], 10).get_page(1),
                    "filters": {
                        "type": "",
                        "start_date": "",
                        "end_date": "",
                        "operator": "",
                    },
                }
            )
            return "web_doctor/partials/checkup_history/list.html"

        mock_handler.side_effect = _fake_handler

        url = reverse(
            "web_doctor:patient_workspace_section",
            args=[self.patient.id, "checkup_history"],
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "web_doctor/partials/checkup_history/list.html")
        self.assertContains(response, "复查/诊疗历史记录")
        self.assertContains(response, "记录类型")
        self.assertContains(response, "搜索")
