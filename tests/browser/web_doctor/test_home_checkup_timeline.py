from datetime import datetime, date
from pathlib import Path

from django.test import tag
from django.utils import timezone

from market.models import Order
from tests.browser.web_doctor.base import DoctorBrowserTestCase, expect


@tag("browser")
class DoctorHomeCheckupTimelineBrowserTests(DoctorBrowserTestCase):
    def setUp(self):
        super().setUp()
        today = timezone.localdate()
        current_month_start = today.replace(day=1)
        if current_month_start.month == 1:
            previous_month_start = date(current_month_start.year - 1, 12, 1)
        else:
            previous_month_start = date(current_month_start.year, current_month_start.month - 1, 1)
        self.current_month = current_month_start.strftime("%Y-%m")
        self.previous_month = previous_month_start.strftime("%Y-%m")
        self.previous_month_report_date = previous_month_start.replace(day=15).isoformat()

        order = Order.objects.get(patient=self.patient)
        order.product.duration_days = 120
        order.product.save(update_fields=["duration_days"])
        order.paid_at = timezone.make_aware(
            datetime.combine(previous_month_start, datetime.min.time()).replace(hour=9),
            timezone.get_current_timezone(),
        )
        order.save(update_fields=["paid_at", "updated_at"])

    def _month_bar(self, month):
        return self.page.locator(
            '#checkup-timeline-month-bars [data-testid="checkup-month-bar"][data-checkup-month="%s"]'
            % month
        )

    def test_non_current_month_create_refreshes_bar_before_details(self):
        self.open_patient_workspace()
        expect(self.page.locator("#checkup-timeline-container")).to_be_visible(timeout=10000)
        expect(self.page.locator("#checkup-timeline-details")).to_contain_text("本月暂无诊疗记录")
        expect(self._month_bar(self.previous_month).locator('[data-testid="checkup-month-count-hospitalization"]')).to_have_count(0)

        self.page.locator("#checkup-timeline-container").get_by_role("button", name="新增记录").click()
        layer = self.page.locator("[data-home-checkup-record-modal-layer]")
        expect(layer.get_by_text("报告日期")).to_be_visible(timeout=10000)

        layer.locator("select").first.select_option("住院")
        layer.locator('input[type="date"]').fill(self.previous_month_report_date)
        image_path = Path(__file__).resolve().parents[3] / "static" / "logo-192.png"
        layer.locator('input[type="file"]').set_input_files(str(image_path))
        expect(layer.locator('img[src^="data:image"]')).to_be_visible(timeout=10000)

        with self.page.expect_response(
            lambda response: "/checkup/timeline/" in response.url
            and ("selected_month=%s" % self.current_month) in response.url
            and response.status == 200
        ):
            layer.get_by_role("button", name="保存").click()

        expect(self._month_bar(self.previous_month).locator('[data-testid="checkup-month-count-hospitalization"]')).to_have_text("1")
        expect(self.page.locator("#checkup-timeline-details")).not_to_contain_text(self.previous_month_report_date)
        expect(self.page.locator("#checkup-timeline-details")).to_contain_text("本月暂无诊疗记录")

        with self.page.expect_response(
            lambda response: "/checkup/timeline/" in response.url
            and ("selected_month=%s" % self.previous_month) in response.url
            and response.status == 200
        ):
            self._month_bar(self.previous_month).click()

        expect(self.page.locator("#checkup-timeline-details")).to_contain_text(self.previous_month_report_date, timeout=10000)
        expect(self.page.locator("#checkup-timeline-details")).to_contain_text("住院")
