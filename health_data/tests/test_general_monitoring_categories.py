from decimal import Decimal

from django.test import SimpleTestCase

from health_data.models import HealthMetric, MetricType
from health_data import utils as metric_utils


class GeneralMonitoringModelTests(SimpleTestCase):
    def test_health_metric_exposes_measurement_context_field(self):
        field_names = {field.name for field in HealthMetric._meta.get_fields()}

        self.assertIn("measurement_context", field_names)

    def test_monitoring_catalog_contains_all_nine_metrics(self):
        try:
            from health_data.services.monitoring_catalog import (
                MONITORING_DEFINITIONS_BY_SLUG,
                get_monitoring_definition_by_slug,
            )
        except ImportError:
            self.fail("统一监测指标目录尚未实现")

        self.assertEqual(len(MONITORING_DEFINITIONS_BY_SLUG), 9)
        self.assertEqual(
            get_monitoring_definition_by_slug("glucose").metric_type,
            MetricType.BLOOD_GLUCOSE,
        )
        self.assertEqual(
            get_monitoring_definition_by_slug("ketone").unit,
            "mmol/L",
        )
        self.assertEqual(
            get_monitoring_definition_by_slug("uric_acid").unit,
            "μmol/L",
        )
        glucose = get_monitoring_definition_by_slug("glucose")
        self.assertEqual(
            glucose.record_route_name,
            "web_patient:record_general_monitoring",
        )
        self.assertEqual(glucose.record_route_slug, "glucose")


class GeneralMonitoringThresholdTests(SimpleTestCase):
    def test_glucose_threshold_boundaries(self):
        self.assertTrue(
            hasattr(metric_utils, "evaluate_glucose_level"),
            "血糖阈值函数尚未实现",
        )
        evaluate = metric_utils.evaluate_glucose_level

        self.assertEqual(evaluate(Decimal("2.99"), "fasting"), 2)
        self.assertEqual(evaluate(Decimal("3.0"), "fasting"), 1)
        self.assertEqual(evaluate(Decimal("3.9"), "fasting"), 0)
        self.assertEqual(evaluate(Decimal("7.0"), "fasting"), 1)
        self.assertEqual(evaluate(Decimal("11.1"), "postprandial_2h"), 1)
        self.assertEqual(evaluate(Decimal("11.1"), "random"), 1)
        self.assertEqual(evaluate(Decimal("11.1"), None), 1)

    def test_blood_ketone_threshold_boundaries(self):
        self.assertTrue(
            hasattr(metric_utils, "evaluate_blood_ketone_level"),
            "血酮阈值函数尚未实现",
        )
        evaluate = metric_utils.evaluate_blood_ketone_level

        self.assertEqual(evaluate(Decimal("0.59")), 0)
        self.assertEqual(evaluate(Decimal("0.6")), 1)
        self.assertEqual(evaluate(Decimal("1.5")), 1)
        self.assertEqual(evaluate(Decimal("1.51")), 2)
        self.assertEqual(evaluate(Decimal("3.0")), 2)
        self.assertEqual(evaluate(Decimal("3.01")), 3)

    def test_uric_acid_threshold_boundary(self):
        self.assertTrue(
            hasattr(metric_utils, "evaluate_uric_acid_level"),
            "尿酸阈值函数尚未实现",
        )
        evaluate = metric_utils.evaluate_uric_acid_level

        self.assertEqual(evaluate(Decimal("420")), 0)
        self.assertEqual(evaluate(Decimal("420.01")), 1)
