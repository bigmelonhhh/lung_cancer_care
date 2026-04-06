from django.template.loader import render_to_string
from django.test import TestCase


class FollowupReviewTemplateTests(TestCase):
    def test_followup_config_form_has_default_hidden_guard_and_htmx_close_hooks(self):
        context = {
            "patient": type("Patient", (), {"id": 1})(),
            "review_indicator": {
                "module_title": "复查指标",
                "title": "核心关注指标",
                "categories": [
                    {
                        "name": "血常规",
                        "total_subtypes": 1,
                        "subtypes": [{"code": "wbc", "name": "白细胞计数"}],
                    }
                ],
                "selected_subtypes": [],
                "charts": [],
            },
        }

        html = render_to_string(
            "web_doctor/partials/indicators/followup_review_monitoring.html",
            context,
        )

        self.assertIn('id="followup-review-config-form"', html)
        self.assertIn('style="display: none;"', html)
        self.assertIn('x-show="configOpen"', html)
        self.assertIn('hx-on:htmx:before-request="configOpen = false"', html)
        self.assertIn('hx-on:htmx:after-request="configOpen = false"', html)
        self.assertNotIn('onclick="this.closest(\'form\').style.display=\'none\'"', html)
