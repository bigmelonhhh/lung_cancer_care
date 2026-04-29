from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from tests.browser.web_doctor.base import DoctorBrowserTestCase, expect
from users import choices
from users.models import DoctorProfile, SalesProfile


class SalesBrowserTestCase(DoctorBrowserTestCase):
    def setUp(self):
        super().setUp()
        self.sales_user = get_user_model().objects.create_user(
            username="browser_sales",
            password="password",
            user_type=choices.UserType.SALES,
            phone="13700002000",
        )
        self.sales = SalesProfile.objects.create(
            user=self.sales_user,
            name="Browser Sales",
            region="华东大区",
            qrcode_url="https://example.com/browser-sales-qrcode.png",
        )
        self.doctor.sales.add(self.sales)
        self.patient.sales = self.sales
        self.patient.qrcode_url = "https://example.com/browser-patient-sales-qrcode.png"
        self.patient.qrcode_expire_at = timezone.now() + timedelta(days=7)
        self.patient.save(
            update_fields=["sales", "qrcode_url", "qrcode_expire_at", "updated_at"]
        )

        self.second_doctor_user = get_user_model().objects.create_user(
            username="browser_sales_doctor_2",
            password="password",
            user_type=choices.UserType.DOCTOR,
            phone="13700002001",
        )
        self.second_doctor = DoctorProfile.objects.create(
            user=self.second_doctor_user,
            name="Browser Doctor Two",
            hospital="Browser Second Hospital",
            department="Thoracic Oncology",
            title="副主任医师",
            studio=self.studio,
        )
        self.second_doctor.sales.add(self.sales)

        self.login_browser_as(self.sales_user)

    def open_sales_dashboard(self):
        self.page.goto(self.url_for("web_sales:sales_dashboard"), wait_until="load")
        self.page.wait_for_function("window.htmx && window.Alpine")


class SalesMobileBrowserTestCase(SalesBrowserTestCase):
    def browser_context_options(self):
        return {
            "base_url": self.live_server_url,
            "viewport": {"width": 390, "height": 844},
            "is_mobile": True,
            "has_touch": True,
            "user_agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
                "Mobile/15E148 Safari/604.1"
            ),
        }
