import re
from datetime import date

from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import TestCase

from core.models import TreatmentCycle
from core.service.china_calendar import ChinaCalendarService
from users.models import PatientProfile
from web_doctor.templatetags.plan_dates import plan_table_max_width_px, plan_table_min_width_px

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

    def _build_plan_view(self, **overrides):
        header_meta = ChinaCalendarService.build_cycle_header_meta(
            start_date=self.cycle.start_date,
            cycle_days=self.cycle.cycle_days,
        )
        plan_view = {
            "current_day_index": 1,
            "monitorings": [],
            "medications": [],
            "checkups": [],
            "questionnaires": [],
            "med_library": [],
            "header_days": header_meta["header_days"],
            "header_week_ranges": header_meta["header_week_ranges"],
        }
        plan_view.update(overrides)
        return plan_view

    def test_header_highlight_dates_and_week_dividers(self):
        html = render_to_string(
            "web_doctor/partials/settings/plan_table.html",
            {
                "patient": self.patient,
                "cycle": self.cycle,
                "is_cycle_editable": True,
                "plan_view": self._build_plan_view(),
            },
        )

        self.assertIn('data-plan-date="01/01"', html)
        self.assertIn('data-plan-date="01/08"', html)
        self.assertIn('data-plan-date="01/15"', html)
        self.assertIn('data-plan-range="1-7"', html)
        self.assertIn('data-plan-range="8-14"', html)
        self.assertIn('data-plan-range="15-21"', html)
        self.assertIn('title="2026-1-1 至 2026-1-7"', html)
        self.assertRegex(html, r">\s*1-1\s*<")
        self.assertRegex(html, r">\s*1-7\s*<")
        self.assertNotIn(">01/01<", html)
        self.assertNotIn(">01/08<", html)
        self.assertNotIn(">01/15<", html)
        self.assertIn('id="plan-day-tooltip"', html)
        self.assertIn("var showDelayMs = 300", html)
        self.assertIn("D2", html)

        self.assertEqual(html.count("border-r border-gray-200"), 3)

    def test_week_dividers_apply_to_all_modules_rows(self):
        plan_view = self._build_plan_view(
            monitorings=[
                {
                    "lib_id": 1,
                    "name": "监测A",
                    "is_active": True,
                    "schedule": [1, 7, 14, 21],
                    "plan_item_id": 1,
                }
            ],
            medications=[
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
            checkups=[
                {
                    "lib_id": 1,
                    "name": "复查A",
                    "is_active": True,
                    "schedule": [7, 14, 21],
                    "plan_item_id": 1,
                }
            ],
            questionnaires=[
                {
                    "lib_id": 1,
                    "name": "问卷A",
                    "is_active": True,
                    "schedule": [7, 14, 21],
                    "plan_item_id": 1,
                }
            ],
        )

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

    def test_editable_plan_table_renders_independent_checkup_and_questionnaire_searches(self):
        plan_view = self._build_plan_view(
            checkups=[
                {
                    "lib_id": 1,
                    "name": "胸部增强CT",
                    "is_active": True,
                    "schedule": [],
                    "plan_item_id": 1,
                }
            ],
            questionnaires=[
                {
                    "lib_id": 2,
                    "name": "睡眠质量量表",
                    "is_active": True,
                    "schedule": [],
                    "plan_item_id": 2,
                }
            ],
        )

        html = render_to_string(
            "web_doctor/partials/settings/plan_table.html",
            {
                "patient": self.patient,
                "cycle": self.cycle,
                "is_cycle_editable": True,
                "plan_view": plan_view,
            },
        )

        self.assertEqual(html.count("data-plan-filter-input"), 2)
        self.assertIn('aria-label="搜索复查类目"', html)
        self.assertIn('aria-label="搜索量表"', html)
        search_inputs = re.findall(r'<input[^>]+data-plan-filter-input[^>]*>', html)
        self.assertEqual(len(search_inputs), 2)
        for search_input in search_inputs:
            self.assertIn("placeholder:text-slate-300", search_input)
            self.assertNotIn("font-normal", search_input)
        self.assertIn('data-plan-filter-text="胸部增强CT"', html)
        self.assertIn('data-plan-filter-text="睡眠质量量表"', html)
        self.assertIn("未找到匹配的复查类目", html)
        self.assertIn("未找到匹配的量表", html)

    def test_readonly_plan_table_does_not_render_search_controls(self):
        html = render_to_string(
            "web_doctor/partials/settings/plan_table.html",
            {
                "patient": self.patient,
                "cycle": self.cycle,
                "is_cycle_editable": False,
                "plan_view": self._build_plan_view(),
            },
        )

        self.assertNotIn("data-plan-filter-input", html)
        self.assertNotIn("data-plan-filter-empty", html)

    def test_28_day_cycle_renders_all_headers_dates_and_dynamic_width(self):
        self.cycle.cycle_days = 28
        self.cycle.save(update_fields=["cycle_days"])

        html = render_to_string(
            "web_doctor/partials/settings/plan_table.html",
            {
                "patient": self.patient,
                "cycle": self.cycle,
                "is_cycle_editable": True,
                "plan_view": self._build_plan_view(),
            },
        )

        self.assertIn('data-plan-day="28"', html)
        self.assertIn('data-plan-date="01/22"', html)
        self.assertIn('data-plan-date="01/28"', html)
        self.assertIn('data-plan-range="22-28"', html)
        self.assertIn('title="2026-1-22 至 2026-1-28"', html)
        self.assertIn("D28", html)
        self.assertIn('colspan="28"', html)
        self.assertIn("min-width: 1280px;", html)
        self.assertEqual(html.count("border-r border-gray-200"), 4)
        self.assertIn('data-plan-label="D22"', html)

    def test_plan_table_width_bounds_cover_supported_cycle_lengths(self):
        expected_widths = {
            2: (448, 464),
            21: (1056, 1224),
            28: (1280, 1504),
            100: (3584, 4384),
        }

        for cycle_days, (expected_min, expected_max) in expected_widths.items():
            with self.subTest(cycle_days=cycle_days):
                self.assertEqual(plan_table_min_width_px(cycle_days), expected_min)
                self.assertEqual(plan_table_max_width_px(cycle_days), expected_max)

    def test_plan_table_renders_split_header_and_sticky_column_markers(self):
        plan_view = self._build_plan_view(
            monitorings=[
                {
                    "lib_id": 1,
                    "name": "监测A",
                    "is_active": True,
                    "schedule": [1, 7, 14, 21],
                    "plan_item_id": 1,
                }
            ]
        )

        html = render_to_string(
            "web_doctor/partials/settings/plan_table.html",
            {
                "patient": self.patient,
                "cycle": self.cycle,
                "is_cycle_editable": True,
                "plan_view": plan_view,
            },
        )

        self.assertIn('data-plan-table-head-clip', html)
        self.assertIn('data-plan-table-body-scroll', html)
        self.assertEqual(len(re.findall(r'<th[^>]*data-plan-sticky-head-col', html)), 3)
        self.assertEqual(len(re.findall(r'<td[^>]*data-plan-sticky-section', html)), 4)
        self.assertIn('data-plan-sticky-col="1"', html)
        self.assertIn('data-plan-sticky-col="2"', html)
        self.assertIn('data-plan-sticky-col="3"', html)
        self.assertIn('style="width: 384px;"', html)
        self.assertIn('--plan-sticky-col-1-width: 12rem;', html)
        self.assertIn('colspan="21"', html)
        self.assertNotIn('<col class="w-8">', html)
        self.assertIn('width: clamp(672px, 100%, 840px);', html)
        self.assertIn('width: clamp(1056px, 100%, 1224px);', html)

    def test_28_day_cycle_adds_week_dividers_for_each_row(self):
        self.cycle.cycle_days = 28
        self.cycle.save(update_fields=["cycle_days"])
        plan_view = self._build_plan_view(
            monitorings=[
                {
                    "lib_id": 1,
                    "name": "监测A",
                    "is_active": True,
                    "schedule": [1, 7, 14, 21, 28],
                    "plan_item_id": 1,
                }
            ],
            medications=[
                {
                    "lib_id": 1,
                    "name": "药品A",
                    "type": "口服",
                    "default_dosage": "1片",
                    "default_frequency": "每日一次",
                    "schedule": [1, 7, 14, 21, 28],
                    "plan_item_id": 1,
                }
            ],
            checkups=[
                {
                    "lib_id": 1,
                    "name": "复查A",
                    "is_active": True,
                    "schedule": [7, 14, 21, 28],
                    "plan_item_id": 1,
                }
            ],
            questionnaires=[
                {
                    "lib_id": 1,
                    "name": "问卷A",
                    "is_active": True,
                    "schedule": [7, 14, 21, 28],
                    "plan_item_id": 1,
                }
            ],
        )

        html = render_to_string(
            "web_doctor/partials/settings/plan_table.html",
            {
                "patient": self.patient,
                "cycle": self.cycle,
                "is_cycle_editable": True,
                "plan_view": plan_view,
            },
        )

        self.assertEqual(html.count("border-r border-gray-200"), 20)

    def test_non_full_last_week_range_uses_cycle_end_day(self):
        self.cycle.start_date = date(2026, 4, 6)
        self.cycle.cycle_days = 10
        self.cycle.save(update_fields=["start_date", "cycle_days"])

        html = render_to_string(
            "web_doctor/partials/settings/plan_table.html",
            {
                "patient": self.patient,
                "cycle": self.cycle,
                "is_cycle_editable": True,
                "plan_view": self._build_plan_view(),
            },
        )

        self.assertIn('data-plan-range="1-7"', html)
        self.assertIn('data-plan-range="8-10"', html)
        self.assertIn('data-plan-range-end-day="10"', html)
        self.assertIn('title="2026-4-13 至 2026-4-15"', html)
        self.assertRegex(html, r">\s*4-13\s*<")
        self.assertRegex(html, r">\s*4-15\s*<")
        self.assertIn('colspan="3"', html)

    def test_weekend_days_are_highlighted_with_reason(self):
        self.cycle.start_date = date(2026, 4, 6)
        self.cycle.cycle_days = 7
        self.cycle.save(update_fields=["start_date", "cycle_days"])

        html = render_to_string(
            "web_doctor/partials/settings/plan_table.html",
            {
                "patient": self.patient,
                "cycle": self.cycle,
                "is_cycle_editable": True,
                "plan_view": self._build_plan_view(),
            },
        )

        self.assertRegex(
            html,
            r'<th(?=[^>]*data-plan-day="6")(?=[^>]*data-plan-day-note="周六")(?=[^>]*title="2026-4-11 · 周六")(?=[^>]*class="[^"]*text-rose-500)[^>]*>',
        )
        self.assertRegex(
            html,
            r'<th(?=[^>]*data-plan-day="7")(?=[^>]*data-plan-day-note="周日")(?=[^>]*title="2026-4-12 · 周日")(?=[^>]*class="[^"]*text-rose-500)[^>]*>',
        )

    def test_statutory_holiday_day_is_highlighted_with_holiday_name(self):
        self.cycle.start_date = date(2026, 4, 29)
        self.cycle.cycle_days = 5
        self.cycle.save(update_fields=["start_date", "cycle_days"])

        html = render_to_string(
            "web_doctor/partials/settings/plan_table.html",
            {
                "patient": self.patient,
                "cycle": self.cycle,
                "is_cycle_editable": True,
                "plan_view": self._build_plan_view(),
            },
        )

        self.assertRegex(
            html,
            r'<th(?=[^>]*data-plan-day="3")(?=[^>]*data-plan-day-note="劳动节")(?=[^>]*title="2026-5-1 · 劳动节")(?=[^>]*class="[^"]*text-rose-500)[^>]*>',
        )
