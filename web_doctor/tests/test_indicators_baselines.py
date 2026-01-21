from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import TestCase
from django.utils import timezone

from users.models import PatientProfile
from web_doctor.views.indicators import build_indicators_context

User = get_user_model()


def _empty_page():
    return SimpleNamespace(object_list=[])


@patch("web_doctor.views.indicators.get_treatment_cycles", return_value=SimpleNamespace(object_list=[]))
@patch("web_doctor.views.indicators.get_adherence_metrics_batch", return_value=[])
@patch("web_doctor.views.indicators.QuestionnaireSubmissionService.list_daily_questionnaire_scores", return_value=[])
@patch("web_doctor.views.indicators.QuestionnaireSubmissionService.list_daily_cough_hemoptysis_flags", return_value=[])
@patch("web_doctor.views.indicators.HealthMetricService.query_metrics_by_type", return_value=_empty_page())
class IndicatorsBaselineTests(TestCase):
    """患者指标-常规监测：基线值下发与图表 markLine 渲染测试"""

    def setUp(self):
        self.user = User.objects.create_user(
            username="testpatient_baseline",
            password="password",
            wx_openid="test_openid_baseline_123",
        )
        self.patient = PatientProfile.objects.create(user=self.user, name="Test Patient Baseline")
        self.today = timezone.localdate()
        self.start_date = self.today - timedelta(days=6)
        self.end_date = self.today

    def _context(self):
        return build_indicators_context(
            self.patient,
            start_date_str=self.start_date.isoformat(),
            end_date_str=self.end_date.isoformat(),
            filter_type="date",
        )

    def _render_chart(self, chart):
        return render_to_string("web_doctor/partials/indicators/chart.html", {"chart": chart})

    def test_spo2_baseline_backend_and_render(self, *_mocks):
        """测试血氧：有基线值时下发 baseline 且渲染 markLine"""
        self.patient.baseline_blood_oxygen = 98
        self.patient.save(update_fields=["baseline_blood_oxygen"])

        context = self._context()
        chart = context["charts"]["spo2"]

        self.assertEqual(chart["series"][0]["baseline"], 98)

        html = self._render_chart(chart)
        self.assertIn("markLine", html)
        self.assertIn("yAxis: 98", html)

    def test_spo2_no_baseline_backend_and_render(self, *_mocks):
        """测试血氧：无基线值时不渲染 markLine"""
        context = self._context()
        chart = context["charts"]["spo2"]

        self.assertIsNone(chart["series"][0]["baseline"])

        html = self._render_chart(chart)
        self.assertNotIn("markLine", html)

    def test_bp_baseline_backend_and_render(self, *_mocks):
        """测试血压：两条基线值分别作用于收缩压/舒张压两条曲线"""
        self.patient.baseline_blood_pressure_sbp = 120
        self.patient.baseline_blood_pressure_dbp = 80
        self.patient.save(update_fields=["baseline_blood_pressure_sbp", "baseline_blood_pressure_dbp"])

        context = self._context()
        chart = context["charts"]["bp"]

        self.assertEqual(chart["series"][0]["baseline"], 120)
        self.assertEqual(chart["series"][1]["baseline"], 80)

        html = self._render_chart(chart)
        self.assertIn("markLine", html)
        self.assertIn("yAxis: 120", html)
        self.assertIn("yAxis: 80", html)

    def test_bp_mixed_baseline_backend_and_render(self, *_mocks):
        """测试血压：仅存在一条基线值时，仅渲染对应曲线的基线横线"""
        self.patient.baseline_blood_pressure_sbp = 120
        self.patient.baseline_blood_pressure_dbp = None
        self.patient.save(update_fields=["baseline_blood_pressure_sbp", "baseline_blood_pressure_dbp"])

        context = self._context()
        chart = context["charts"]["bp"]

        self.assertEqual(chart["series"][0]["baseline"], 120)
        self.assertIsNone(chart["series"][1]["baseline"])

        html = self._render_chart(chart)
        self.assertIn("yAxis: 120", html)
        self.assertNotIn("yAxis: 80", html)

    def test_hr_baseline_backend_and_render(self, *_mocks):
        """测试心率：有基线值时下发 baseline 且渲染 markLine"""
        self.patient.baseline_heart_rate = 72
        self.patient.save(update_fields=["baseline_heart_rate"])

        context = self._context()
        chart = context["charts"]["hr"]

        self.assertEqual(chart["series"][0]["baseline"], 72)

        html = self._render_chart(chart)
        self.assertIn("markLine", html)
        self.assertIn("yAxis: 72", html)

    def test_hr_no_baseline_backend_and_render(self, *_mocks):
        """测试心率：无基线值时不渲染 markLine"""
        context = self._context()
        chart = context["charts"]["hr"]

        self.assertIsNone(chart["series"][0]["baseline"])

        html = self._render_chart(chart)
        self.assertNotIn("markLine", html)

    def test_weight_baseline_backend_and_render(self, *_mocks):
        """测试体重：有基线值时下发 baseline 且渲染 markLine"""
        self.patient.baseline_weight = Decimal("68.5")
        self.patient.save(update_fields=["baseline_weight"])

        context = self._context()
        chart = context["charts"]["weight"]

        self.assertEqual(chart["series"][0]["baseline"], Decimal("68.5"))

        html = self._render_chart(chart)
        self.assertIn("markLine", html)
        self.assertIn("yAxis: 68.5", html)

    def test_weight_no_baseline_backend_and_render(self, *_mocks):
        """测试体重：无基线值时不渲染 markLine"""
        context = self._context()
        chart = context["charts"]["weight"]

        self.assertIsNone(chart["series"][0]["baseline"])

        html = self._render_chart(chart)
        self.assertNotIn("markLine", html)

    def test_temp_baseline_backend_and_render(self, *_mocks):
        """测试体温：有基线值时下发 baseline 且渲染 markLine"""
        self.patient.baseline_body_temperature = Decimal("36.5")
        self.patient.save(update_fields=["baseline_body_temperature"])

        context = self._context()
        chart = context["charts"]["temp"]

        self.assertEqual(chart["series"][0]["baseline"], Decimal("36.5"))

        html = self._render_chart(chart)
        self.assertIn("markLine", html)
        self.assertIn("yAxis: 36.5", html)

    def test_temp_no_baseline_backend_and_render(self, *_mocks):
        """测试体温：无基线值时不渲染 markLine"""
        context = self._context()
        chart = context["charts"]["temp"]

        self.assertIsNone(chart["series"][0]["baseline"])

        html = self._render_chart(chart)
        self.assertNotIn("markLine", html)

    def test_steps_baseline_backend_and_render(self, *_mocks):
        """测试步数：有基线值时下发 baseline 且渲染 markLine"""
        self.patient.baseline_steps = 6000
        self.patient.save(update_fields=["baseline_steps"])

        context = self._context()
        chart = context["charts"]["steps"]

        self.assertEqual(chart["series"][0]["baseline"], 6000)

        html = self._render_chart(chart)
        self.assertIn("markLine", html)
        self.assertIn("yAxis: 6000", html)

    def test_steps_no_baseline_backend_and_render(self, *_mocks):
        """测试步数：无基线值时不渲染 markLine"""
        context = self._context()
        chart = context["charts"]["steps"]

        self.assertIsNone(chart["series"][0]["baseline"])

        html = self._render_chart(chart)
        self.assertNotIn("markLine", html)

    def test_mixed_baselines_across_all_charts(self, *_mocks):
        """测试混合场景：部分指标有基线值，只有对应图表渲染基线横线"""
        self.patient.baseline_blood_oxygen = 98
        self.patient.baseline_heart_rate = None
        self.patient.baseline_weight = Decimal("68.5")
        self.patient.baseline_body_temperature = None
        self.patient.baseline_steps = 6000
        self.patient.baseline_blood_pressure_sbp = None
        self.patient.baseline_blood_pressure_dbp = 80
        self.patient.save(
            update_fields=[
                "baseline_blood_oxygen",
                "baseline_heart_rate",
                "baseline_weight",
                "baseline_body_temperature",
                "baseline_steps",
                "baseline_blood_pressure_sbp",
                "baseline_blood_pressure_dbp",
            ]
        )

        context = self._context()

        html_spo2 = self._render_chart(context["charts"]["spo2"])
        html_bp = self._render_chart(context["charts"]["bp"])
        html_hr = self._render_chart(context["charts"]["hr"])
        html_weight = self._render_chart(context["charts"]["weight"])
        html_temp = self._render_chart(context["charts"]["temp"])
        html_steps = self._render_chart(context["charts"]["steps"])

        self.assertIn("yAxis: 98", html_spo2)
        self.assertIn("yAxis: 80", html_bp)
        self.assertNotIn("yAxis: 120", html_bp)
        self.assertNotIn("markLine", html_hr)
        self.assertIn("yAxis: 68.5", html_weight)
        self.assertNotIn("markLine", html_temp)
        self.assertIn("yAxis: 6000", html_steps)

