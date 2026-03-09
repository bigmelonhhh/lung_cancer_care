from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from users.models import DoctorProfile, PatientProfile

User = get_user_model()


class PatientWorkspaceSectionExtraPagesTests(TestCase):
    def setUp(self):
        self.doctor_user = User.objects.create_user(
            username="doc_workspace_sections_extra",
            password="password",
            user_type=2,
            phone="13900139071",
        )
        self.doctor_profile = DoctorProfile.objects.create(
            user=self.doctor_user,
            name="Dr. Workspace Extra",
        )
        self.doctor_user.doctor_profile = self.doctor_profile
        self.doctor_user.save()

        self.patient = PatientProfile.objects.create(
            name="患者工作区扩展",
            phone="13800138271",
            doctor=self.doctor_profile,
        )
        self.client.force_login(self.doctor_user)

    @patch("web_doctor.views.indicators.build_indicators_context", return_value={})
    def test_indicators_section_contains_core_ui_elements(self, _mock_context):
        url = reverse(
            "web_doctor:patient_workspace_section",
            args=[self.patient.id, "indicators"],
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "web_doctor/partials/indicators/indicators.html")
        self.assertContains(response, 'id="indicators-wrapper"')
        self.assertContains(response, "常规监测指标")
        self.assertContains(response, "随访问卷")
        self.assertContains(response, "患者指标")
        self.assertContains(response, 'hx-swap-oob="true"')

    @patch("web_doctor.views.management_stats.ManagementStatsView.get_context_data")
    def test_statistics_section_contains_core_ui_elements(self, mock_get_context_data):
        mock_get_context_data.return_value = {
            "service_packages": [],
            "stats_overview": {
                "medication_adjustment": 0,
                "medication_taken": 0,
                "medication_compliance": "0%",
                "indicators_monitoring": 0,
                "indicators_recorded": 0,
                "monitoring_compliance": "0%",
                "online_consultation": 0,
                "follow_up": 0,
                "checkup": 0,
                "hospitalization": 0,
            },
            "charts": {},
            "query_stats": {
                "total_count": 0,
                "line_chart": {"id": "query-line-chart", "xAxis": [], "series": []},
                "pie_chart": {"id": "query-pie-chart", "series": []},
            },
        }

        url = reverse(
            "web_doctor:patient_workspace_section",
            args=[self.patient.id, "statistics"],
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response, "web_doctor/partials/management_stats/management_stats.html"
        )
        self.assertContains(response, "患者服务包")
        self.assertContains(response, "管理数据概览")
        self.assertContains(response, "管理数据统计")
        self.assertContains(response, "咨询数据统计")
        self.assertContains(response, "在线咨询次数")
        self.assertContains(response, "管理统计")
        self.assertContains(response, 'hx-swap-oob="true"')

