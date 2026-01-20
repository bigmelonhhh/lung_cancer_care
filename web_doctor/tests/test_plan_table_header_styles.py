from datetime import date

from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import TestCase

from core.models import TreatmentCycle
from users.models import PatientProfile

User = get_user_model()


class PlanTableHeaderStylesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testpatient_plan_table",
            password="password",
            wx_openid="test_openid_plan_table_123",
        )
        self.patient = PatientProfile.objects.create(user=self.user, name="Test Patient Plan Table")
        self.cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="Cycle 1",
            start_date=date(2026, 1, 1),
            cycle_days=21,
        )

    def test_header_highlight_dates_and_week_dividers(self):
        html = render_to_string(
            "web_doctor/partials/settings/plan_table.html",
            {
                "patient": self.patient,
                "cycle": self.cycle,
                "is_cycle_editable": True,
                "plan_view": {
                    "current_day_index": 1,
                    "monitorings": [],
                    "medications": [],
                    "checkups": [],
                    "questionnaires": [],
                    "med_library": [],
                },
            },
        )

        self.assertIn("01/01", html)
        self.assertIn("01/08", html)
        self.assertIn("01/15", html)
        self.assertIn("D2", html)

        self.assertEqual(html.count("border-r border-gray-200"), 3)

    def test_week_dividers_apply_to_all_modules_rows(self):
        plan_view = {
            "current_day_index": 1,
            "monitorings": [
                {
                    "lib_id": 1,
                    "name": "监测A",
                    "is_active": True,
                    "schedule": [1, 7, 14, 21],
                    "plan_item_id": 1,
                }
            ],
            "medications": [
                {
                    "lib_id": 1,
                    "name": "药品A",
                    "type": "口服",
                    "default_dosage": "1片",
                    "default_frequency": "每日一次",
                    "schedule": [1, 7, 14, 21],
                    "plan_item_id": 1,
                }
            ],
            "checkups": [
                {
                    "lib_id": 1,
                    "name": "复查A",
                    "is_active": True,
                    "schedule": [7, 14, 21],
                    "plan_item_id": 1,
                }
            ],
            "questionnaires": [
                {
                    "lib_id": 1,
                    "name": "问卷A",
                    "is_active": True,
                    "schedule": [7, 14, 21],
                    "plan_item_id": 1,
                }
            ],
            "med_library": [],
        }

        html = render_to_string(
            "web_doctor/partials/settings/plan_table.html",
            {
                "patient": self.patient,
                "cycle": self.cycle,
                "is_cycle_editable": True,
                "plan_view": plan_view,
            },
        )

        self.assertEqual(html.count("border-r border-gray-200"), 15)
