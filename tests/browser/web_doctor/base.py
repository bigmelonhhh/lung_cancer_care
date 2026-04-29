import os
from decimal import Decimal
from urllib.parse import urljoin

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse
from django.utils import timezone

from market.models import Order, Product
from users import choices
from users.models import DoctorProfile, DoctorStudio, PatientProfile

os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import expect, sync_playwright
except ModuleNotFoundError:
    PlaywrightError = Exception
    expect = None
    sync_playwright = None


class DoctorBrowserTestCase(StaticLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if sync_playwright is None:
            raise RuntimeError(
                "Python Playwright is not installed. Run: pip install -r requirements.txt"
            )

        headless = os.getenv("PLAYWRIGHT_HEADLESS", "1").lower() not in {"0", "false", "no"}
        cls._playwright = sync_playwright().start()
        try:
            cls.browser = cls._playwright.chromium.launch(headless=headless)
        except PlaywrightError as exc:
            cls._playwright.stop()
            raise RuntimeError(
                "Playwright Chromium is not installed. Run: python -m playwright install chromium"
            ) from exc

    @classmethod
    def tearDownClass(cls):
        try:
            if getattr(cls, "browser", None):
                cls.browser.close()
        finally:
            if getattr(cls, "_playwright", None):
                cls._playwright.stop()
            super().tearDownClass()

    def setUp(self):
        self.doctor_user = get_user_model().objects.create_user(
            username="browser_doctor",
            password="password",
            user_type=choices.UserType.DOCTOR,
            phone="13800002000",
        )
        self.doctor = DoctorProfile.objects.create(
            user=self.doctor_user,
            name="Browser Doctor",
            hospital="Browser Hospital",
            department="Oncology",
            title="主任医师",
        )
        self.studio = DoctorStudio.objects.create(
            name="Browser Studio",
            code="BROWSER_STUDIO",
            owner_doctor=self.doctor,
        )
        self.doctor.studio = self.studio
        self.doctor.save(update_fields=["studio"])
        self.patient_user = get_user_model().objects.create_user(
            username="browser_patient",
            user_type=choices.UserType.PATIENT,
            wx_openid="browser_patient_openid",
        )
        self.patient = PatientProfile.objects.create(
            user=self.patient_user,
            name="Browser Patient",
            phone="13900002000",
            doctor=self.doctor,
        )
        product = Product.objects.create(
            name="Browser VIP",
            price=Decimal("199.00"),
            duration_days=30,
            is_active=True,
        )
        Order.objects.create(
            patient=self.patient,
            product=product,
            amount=Decimal("199.00"),
            status=Order.Status.PAID,
            paid_at=timezone.now(),
        )

        self.client.force_login(self.doctor_user)
        self.context = self.browser.new_context(**self.browser_context_options())
        self._copy_django_session_cookie()
        self.page = self.context.new_page()

    def tearDown(self):
        self.context.close()

    def _copy_django_session_cookie(self):
        session_cookie = self.client.cookies.get(settings.SESSION_COOKIE_NAME)
        self.assertIsNotNone(session_cookie)
        self.context.add_cookies(
            [
                {
                    "name": settings.SESSION_COOKIE_NAME,
                    "value": session_cookie.value,
                    "url": self.live_server_url,
                    "httpOnly": True,
                    "sameSite": "Lax",
                }
            ]
        )

    def login_browser_as(self, user):
        self.client.force_login(user)
        self.page.close()
        self.context.close()
        self.context = self.browser.new_context(**self.browser_context_options())
        self._copy_django_session_cookie()
        self.page = self.context.new_page()

    def browser_context_options(self):
        return {
            "base_url": self.live_server_url,
            "viewport": {"width": 1440, "height": 900},
        }

    def url_for(self, view_name, *args):
        return urljoin(self.live_server_url, reverse(view_name, args=args))

    def open_doctor_workspace(self):
        self.page.goto(self.url_for("web_doctor:doctor_workspace"), wait_until="domcontentloaded")
        self.page.wait_for_function("window.htmx && window.Alpine")

    def open_patient_workspace(self):
        self.open_doctor_workspace()
        self.page.locator('[data-patient-item][data-patient-id="%s"]' % self.patient.id).click()
        expect(self.page.locator("#patient-content")).to_contain_text("概况", timeout=10000)
