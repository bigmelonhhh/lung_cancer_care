from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from django.urls import reverse

from core.models import TreatmentCycle, choices
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
        self.assertContains(response, 'id="routine-filter-form"')
        self.assertContains(response, 'hx-target="#patient-content"')
        self.assertContains(response, 'hx-swap="innerHTML"')
        self.assertContains(response, 'hx-indicator="#workspace-loading-overlay"')
        self.assertNotContains(response, 'hx-target="#indicators-wrapper"')

    @patch("web_doctor.views.indicators.get_adherence_metrics_batch", return_value=[])
    @patch("web_doctor.views.indicators.QuestionnaireSubmissionService.list_daily_questionnaire_scores", return_value=[])
    @patch("web_doctor.views.indicators.QuestionnaireSubmissionService.list_daily_cough_hemoptysis_flags", return_value=[])
    @patch("web_doctor.views.indicators.HealthMetricService.query_metrics_by_type", return_value=SimpleNamespace(object_list=[]))
    def test_indicators_date_filter_response_preserves_filter_controls(self, *_mocks):
        start_date = timezone.localdate() - timedelta(days=6)
        end_date = timezone.localdate()
        url = reverse(
            "web_doctor:patient_workspace_section",
            args=[self.patient.id, "indicators"],
        )
        response = self.client.get(
            url,
            {
                "filter_type": "date",
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="indicators-wrapper"')
        self.assertContains(response, 'data-routine-filter-form')
        self.assertContains(response, 'data-routine-filter-type')
        self.assertContains(response, '<option value="date" selected', html=False)
        self.assertContains(response, f'value="{start_date.isoformat()}"')
        self.assertContains(response, f'value="{end_date.isoformat()}"')
        self.assertContains(response, 'data-routine-filter-panel="date"')
        self.assertContains(response, 'hx-target="#patient-content"')
        self.assertContains(response, 'hx-swap="innerHTML"')

    @patch("web_doctor.views.indicators.get_adherence_metrics_batch", return_value=[])
    @patch("web_doctor.views.indicators.QuestionnaireSubmissionService.list_daily_questionnaire_scores", return_value=[])
    @patch("web_doctor.views.indicators.QuestionnaireSubmissionService.list_daily_cough_hemoptysis_flags", return_value=[])
    @patch("web_doctor.views.indicators.HealthMetricService.query_metrics_by_type", return_value=SimpleNamespace(object_list=[]))
    def test_indicators_cycle_filter_response_preserves_filter_controls(self, *_mocks):
        today = timezone.localdate()
        first_cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="第一疗程",
            start_date=today - timedelta(days=20),
            end_date=today - timedelta(days=10),
            status=choices.TreatmentCycleStatus.COMPLETED,
        )
        selected_cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="中间疗程",
            start_date=today - timedelta(days=9),
            end_date=today,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        TreatmentCycle.objects.create(
            patient=self.patient,
            name="后续疗程",
            start_date=today + timedelta(days=1),
            end_date=today + timedelta(days=10),
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        url = reverse(
            "web_doctor:patient_workspace_section",
            args=[self.patient.id, "indicators"],
        )
        response = self.client.get(
            url,
            {
                "filter_type": "cycle",
                "cycle_id": str(selected_cycle.id),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="indicators-wrapper"')
        self.assertContains(response, 'data-routine-filter-form')
        self.assertContains(response, '<option value="cycle" selected', html=False)
        self.assertContains(response, 'data-routine-filter-panel="cycle"')
        self.assertContains(response, f'<option value="{selected_cycle.id}"', html=False)
        self.assertContains(response, f'data-start="{selected_cycle.start_date.isoformat()}"')
        self.assertContains(response, f'data-end="{selected_cycle.end_date.isoformat()}"')
        self.assertContains(response, "中间疗程")
        self.assertContains(response, 'selected')
        self.assertContains(response, 'hx-target="#patient-content"')
        self.assertContains(response, 'hx-swap="innerHTML"')
        self.assertContains(response, f'<option value="{first_cycle.id}"', html=False)

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
