from datetime import timedelta

from django.utils import timezone

from tests.browser.web_doctor.base import DoctorBrowserTestCase, expect


class PatientBrowserTestCase(DoctorBrowserTestCase):
    def setUp(self):
        super().setUp()
        self.patient.qrcode_url = "https://example.com/browser-patient-qrcode.png"
        self.patient.qrcode_expire_at = timezone.now() + timedelta(days=7)
        self.patient.save(update_fields=["qrcode_url", "qrcode_expire_at", "updated_at"])
        self.login_browser_as(self.patient_user)

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
