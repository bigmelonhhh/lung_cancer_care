from datetime import date
from decimal import Decimal

from django.test import tag

from core.models import CheckupFieldMapping, CheckupLibrary, StandardField, StandardFieldValueType
from health_data.models import (
    CheckupResultAbnormalFlag,
    CheckupResultValue,
    ClinicalEvent,
    ReportImage,
    ReportUpload,
    UploadSource,
)
from tests.browser.web_doctor.base import DoctorBrowserTestCase, expect


@tag("browser")
class DoctorReportsHistoryMetricsBrowserTests(DoctorBrowserTestCase):
    def setUp(self):
        super().setUp()
        self.checkup_item = CheckupLibrary.objects.create(name="血常规", code="BROWSER_BLOOD_ROUTINE")
        self.wbc_field = StandardField.objects.create(
            local_code="WBC_BROWSER_UP",
            english_abbr="WBC-B",
            chinese_name="白细胞计数浏览器测试",
            value_type=StandardFieldValueType.DECIMAL,
            default_unit="10^9/L",
        )
        self.rbc_field = StandardField.objects.create(
            local_code="RBC_BROWSER_DOWN",
            english_abbr="RBC-B",
            chinese_name="红细胞计数浏览器测试",
            value_type=StandardFieldValueType.DECIMAL,
            default_unit="10^12/L",
        )
        CheckupFieldMapping.objects.create(
            checkup_item=self.checkup_item,
            standard_field=self.wbc_field,
            sort_order=10,
        )
        CheckupFieldMapping.objects.create(
            checkup_item=self.checkup_item,
            standard_field=self.rbc_field,
            sort_order=20,
        )

        previous_upload = ReportUpload.objects.create(
            patient=self.patient,
            upload_source=UploadSource.DOCTOR_BACKEND,
        )
        current_upload = ReportUpload.objects.create(
            patient=self.patient,
            upload_source=UploadSource.DOCTOR_BACKEND,
        )
        self.current_event = ClinicalEvent.objects.create(
            patient=self.patient,
            event_type=3,
            event_date=date(2026, 4, 1),
            created_by_doctor=self.doctor,
            interpretation="浏览器指标高亮测试",
        )
        previous_image = ReportImage.objects.create(
            upload=previous_upload,
            image_url="/static/logo-192.png",
            record_type=ReportImage.RecordType.CHECKUP,
            checkup_item=self.checkup_item,
            report_date=date(2026, 3, 25),
        )
        self.current_image = ReportImage.objects.create(
            upload=current_upload,
            image_url="/static/logo-192.png",
            record_type=ReportImage.RecordType.CHECKUP,
            checkup_item=self.checkup_item,
            clinical_event=self.current_event,
            report_date=self.current_event.event_date,
        )
        self._create_result(previous_image, self.wbc_field, "4.8", "10^9/L", "3.5", "9.5")
        self._create_result(previous_image, self.rbc_field, "5.2", "10^12/L", "4.3", "5.8")
        self._create_result(self.current_image, self.wbc_field, "6.3", "10^9/L", "3.5", "9.5")
        self._create_result(self.current_image, self.rbc_field, "4.8", "10^12/L", "4.3", "5.8")

    def _create_result(self, report_image, standard_field, value, unit, lower, upper):
        return CheckupResultValue.objects.create(
            patient=self.patient,
            report_image=report_image,
            checkup_item=self.checkup_item,
            standard_field=standard_field,
            report_date=report_image.report_date,
            raw_name=standard_field.chinese_name,
            normalized_name=standard_field.chinese_name,
            raw_value=value,
            value_numeric=Decimal(value),
            unit=unit,
            lower_bound=Decimal(lower),
            upper_bound=Decimal(upper),
            range_text=f"{lower}-{upper}",
            abnormal_flag=CheckupResultAbnormalFlag.NORMAL,
        )

    def _open_metric_detail(self):
        self.open_patient_workspace()
        self.page.get_by_test_id("workspace-tab-reports").click()
        expect(self.page.get_by_test_id("reports-history-content")).to_be_visible(timeout=10000)

        self.page.locator(f"#report-row-summary-{self.current_event.id}").click()
        detail = self.page.locator(f"#report-detail-body-{self.current_event.id}")
        metric_button = detail.get_by_role("button", name="查看指标数据")
        expect(metric_button).to_be_visible(timeout=10000)

        metric_button.click()
        expect(detail.locator("table")).to_contain_text("WBC_BROWSER_UP", timeout=10000)
        expect(detail.locator("table")).to_contain_text("RBC_BROWSER_DOWN")
        return detail

    def test_content_fragment_detail_expand_has_reports_loader_from_workspace_shell(self):
        console_failures = []
        self.page.on(
            "console",
            lambda message: console_failures.append(message.text)
            if message.type in ("error", "warning")
            and (
                "loadReportsDetail is not a function" in message.text
                or "Alpine Expression Error" in message.text
            )
            else None,
        )
        self.page.on("pageerror", lambda error: console_failures.append(str(error)))

        self.open_doctor_workspace()
        fragment_url = (
            self.url_for("web_doctor:patient_workspace_section", self.patient.id, "reports")
            + "?tab=records&fragment=content"
        )
        self.page.evaluate(
            """async ({ url }) => {
                const response = await fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" } });
                const html = await response.text();
                const main = document.getElementById("main-content");
                main.innerHTML = `<div id="reports-history-content" data-testid="reports-history-content">${html}</div>`;
                if (window.htmx) window.htmx.process(main);
                if (window.Alpine) window.Alpine.initTree(main);
            }""",
            {"url": fragment_url},
        )

        expect(self.page.locator(f"#report-row-summary-{self.current_event.id}")).to_be_visible(timeout=10000)
        self.page.locator(f"#report-row-summary-{self.current_event.id}").click()
        detail = self.page.locator(f"#report-detail-body-{self.current_event.id}")
        expect(detail).to_contain_text("报告备注与解读", timeout=10000)
        self.assertEqual(console_failures, [])

    def test_metric_previous_and_delta_cells_use_delta_direction_highlight(self):
        detail = self._open_metric_detail()

        wbc_cells = detail.locator("tbody tr", has_text="WBC_BROWSER_UP").locator("td")
        self.assertIn("text-slate-700", wbc_cells.nth(2).get_attribute("class") or "")
        expect(wbc_cells.nth(2).locator("svg.icon").nth(0)).to_be_hidden()
        expect(wbc_cells.nth(2).locator("svg.icon").nth(1)).to_be_hidden()
        self.assertIn("bg-rose-100", wbc_cells.nth(5).get_attribute("class") or "")
        self.assertIn("bg-rose-100", wbc_cells.nth(6).get_attribute("class") or "")

        rbc_cells = detail.locator("tbody tr", has_text="RBC_BROWSER_DOWN").locator("td")
        self.assertIn("text-slate-700", rbc_cells.nth(2).get_attribute("class") or "")
        expect(rbc_cells.nth(2).locator("svg.icon").nth(0)).to_be_hidden()
        expect(rbc_cells.nth(2).locator("svg.icon").nth(1)).to_be_hidden()
        self.assertIn("bg-sky-100", rbc_cells.nth(5).get_attribute("class") or "")
        self.assertIn("bg-sky-100", rbc_cells.nth(6).get_attribute("class") or "")

    def test_metric_current_result_cells_show_reference_range_arrows(self):
        CheckupResultValue.objects.filter(
            report_image=self.current_image,
            standard_field=self.wbc_field,
        ).update(abnormal_flag=CheckupResultAbnormalFlag.HIGH)
        CheckupResultValue.objects.filter(
            report_image=self.current_image,
            standard_field=self.rbc_field,
        ).update(abnormal_flag=CheckupResultAbnormalFlag.LOW)

        detail = self._open_metric_detail()

        wbc_cells = detail.locator("tbody tr", has_text="WBC_BROWSER_UP").locator("td")
        self.assertIn("bg-rose-100", wbc_cells.nth(2).get_attribute("class") or "")
        expect(wbc_cells.nth(2).locator("svg.icon").nth(0)).to_be_visible()
        expect(wbc_cells.nth(2).locator("svg.icon").nth(1)).to_be_hidden()

        rbc_cells = detail.locator("tbody tr", has_text="RBC_BROWSER_DOWN").locator("td")
        self.assertIn("bg-sky-100", rbc_cells.nth(2).get_attribute("class") or "")
        expect(rbc_cells.nth(2).locator("svg.icon").nth(0)).to_be_hidden()
        expect(rbc_cells.nth(2).locator("svg.icon").nth(1)).to_be_visible()
        self.assertIn("bg-sky-100", rbc_cells.nth(5).get_attribute("class") or "")
        self.assertIn("bg-sky-100", rbc_cells.nth(6).get_attribute("class") or "")
