from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from core.models import TreatmentCycle, choices
from users.models import PatientProfile
from web_doctor.views import indicators

User = get_user_model()


def _empty_page():
    return SimpleNamespace(object_list=[])


@patch("web_doctor.views.indicators.cache.get", return_value=None)
@patch("web_doctor.views.indicators.cache.set", return_value=None)
@patch("web_doctor.views.indicators.get_adherence_metrics_batch", return_value=[])
@patch("web_doctor.views.indicators.QuestionnaireSubmissionService.list_daily_questionnaire_scores", return_value=[])
@patch("web_doctor.views.indicators.QuestionnaireSubmissionService.list_daily_cough_hemoptysis_flags", return_value=[])
@patch("web_doctor.views.indicators.HealthMetricService.query_metrics_by_type", return_value=_empty_page())
class IndicatorsCycleSortingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testpatient_cycle_sorting",
            password="password",
            wx_openid="test_openid_cycle_sorting_123",
        )
        self.patient = PatientProfile.objects.create(user=self.user, name="Test Patient Cycle Sorting")

    def test_get_treatment_cycles_sorts_by_runtime_state_priority(self, *_mocks):
        today = timezone.localdate()
        cycles = [
            TreatmentCycle(
                patient=self.patient,
                name="已终止疗程",
                start_date=today - timedelta(days=5),
                end_date=today + timedelta(days=10),
                cycle_days=21,
                status=choices.TreatmentCycleStatus.TERMINATED,
            ),
            TreatmentCycle(
                patient=self.patient,
                name="已结束疗程",
                start_date=today - timedelta(days=30),
                end_date=today - timedelta(days=10),
                cycle_days=21,
                status=choices.TreatmentCycleStatus.IN_PROGRESS,
            ),
            TreatmentCycle(
                patient=self.patient,
                name="未来疗程",
                start_date=today + timedelta(days=10),
                end_date=today + timedelta(days=30),
                cycle_days=21,
                status=choices.TreatmentCycleStatus.IN_PROGRESS,
            ),
            TreatmentCycle(
                patient=self.patient,
                name="进行中疗程",
                start_date=today - timedelta(days=2),
                end_date=today + timedelta(days=5),
                cycle_days=21,
                status=choices.TreatmentCycleStatus.IN_PROGRESS,
            ),
        ]

        with patch("web_doctor.views.indicators._get_treatment_cycles", return_value=SimpleNamespace(object_list=cycles)):
            page = indicators.get_treatment_cycles(self.patient, page=1, page_size=10)

        self.assertEqual(
            [c.name for c in page.object_list],
            ["进行中疗程", "未来疗程", "已结束疗程", "已终止疗程"],
        )

    def test_build_indicators_context_exposes_sorted_treatment_cycles(self, *_mocks):
        today = timezone.localdate()
        cycles = [
            TreatmentCycle(
                patient=self.patient,
                name="已结束疗程",
                start_date=today - timedelta(days=30),
                end_date=today - timedelta(days=10),
                cycle_days=21,
                status=choices.TreatmentCycleStatus.IN_PROGRESS,
            ),
            TreatmentCycle(
                patient=self.patient,
                name="进行中疗程",
                start_date=today - timedelta(days=2),
                end_date=today + timedelta(days=5),
                cycle_days=21,
                status=choices.TreatmentCycleStatus.IN_PROGRESS,
            ),
            TreatmentCycle(
                patient=self.patient,
                name="已终止疗程",
                start_date=today - timedelta(days=5),
                end_date=today + timedelta(days=10),
                cycle_days=21,
                status=choices.TreatmentCycleStatus.TERMINATED,
            ),
        ]

        with patch("web_doctor.views.indicators._get_treatment_cycles", return_value=SimpleNamespace(object_list=cycles)):
            context = indicators.build_indicators_context(
                self.patient,
                start_date_str=(today - timedelta(days=1)).isoformat(),
                end_date_str=today.isoformat(),
                filter_type="date",
            )

        self.assertEqual(
            [c.name for c in context["treatment_cycles"]],
            ["进行中疗程", "已结束疗程", "已终止疗程"],
        )

