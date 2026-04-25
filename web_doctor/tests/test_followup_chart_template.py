from django.template.loader import render_to_string
from django.test import TestCase


class FollowupChartTemplateTests(TestCase):
    def test_followup_chart_only_renders_title_header(self):
        chart = {
            "id": "chart-followup-review-0",
            "title": "白细胞计数",
            "subtitle": "2026-01-01 ~ 2026-01-07",
            "dates": ["01-01", "01-02", "01-03"],
            "series": [
                {
                    "name": "白细胞计数",
                    "data": [10, 12, 11],
                    "color": "#2563eb",
                }
            ],
            "y_min": 0,
            "y_max": 30,
            "compliance": 88,
        }

        html = render_to_string(
            "web_doctor/partials/indicators/followup_chart.html",
            {"chart": chart},
        )

        self.assertIn("白细胞计数", html)
        self.assertNotIn("2026-01-01 ~ 2026-01-07", html)
        self.assertNotIn("依从性：", html)
        self.assertNotIn("viewBox=\"0 0 24 24\"", html)
