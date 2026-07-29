import importlib

from django.test import TestCase

from core.models import MonitoringTemplate
from core.service.plan_item import PlanItemService


class GeneralMonitoringTemplateMigrationTest(TestCase):
    def test_seed_is_idempotent_and_keeps_expected_defaults(self):
        migration = importlib.import_module(
            "core.migrations.0033_seed_general_monitoring_templates"
        )

        class Apps:
            @staticmethod
            def get_model(app_label, model_name):
                self.assertEqual((app_label, model_name), ("core", "MonitoringTemplate"))
                return MonitoringTemplate

        migration.seed_templates(Apps(), None)
        migration.seed_templates(Apps(), None)

        templates = {
            item.code: item
            for item in MonitoringTemplate.objects.filter(
                code__in=["M_GLU", "M_KETONE", "M_UA"]
            )
        }
        self.assertEqual(len(templates), 3)
        self.assertEqual(templates["M_GLU"].name, "血糖监测")
        self.assertEqual(templates["M_KETONE"].sort_order, 80)
        self.assertEqual(templates["M_UA"].schedule_days_template, list(range(1, 22, 2)))

    def test_monitoring_schedule_is_clipped_to_cycle_length(self):
        template, _ = MonitoringTemplate.objects.get_or_create(
            code="M_GLU",
            defaults={
                "name": "血糖监测",
                "metric_type": "M_GLU",
                "schedule_days_template": list(range(1, 22, 2)),
                "is_active": True,
                "sort_order": 70,
            },
        )
        payload = PlanItemService._build_monitoring_payload(
            template,
            plan=None,
            cycle_days=10,
        )

        self.assertEqual(payload["schedule_days_template"], [1, 3, 5, 7, 9])
        self.assertEqual(payload["schedule_days"], [1, 3, 5, 7, 9])
