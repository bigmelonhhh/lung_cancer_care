from datetime import date
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase

from health_data.admin import ReportImageAdmin
from health_data.models import ReportImage, ReportUpload
from users.models import CustomUser, PatientProfile


class ReportImageAdminTests(TestCase):
    def setUp(self):
        self.site = AdminSite()
        self.factory = RequestFactory()
        self.admin_user = CustomUser.objects.create_superuser(
            username="ai_admin",
            password="strong-pass-123",
            phone="13900004000",
        )
        self.patient = PatientProfile.objects.create(phone="13900004001", name="Admin患者")
        self.upload = ReportUpload.objects.create(patient=self.patient)
        self.image = ReportImage.objects.create(
            upload=self.upload,
            image_url="https://example.com/admin-image.png",
            record_type=ReportImage.RecordType.CHECKUP,
            report_date=date(2026, 4, 16),
        )

    def _build_request(self):
        request = self.factory.post("/admin/")
        SessionMiddleware(lambda req: None).process_request(request)
        request.session.save()
        request.user = self.admin_user
        request._messages = FallbackStorage(request)
        return request

    @patch("ai_vision.tasks.extract_report_image_task.delay")
    def test_admin_action_enqueues_ai_extraction(self, mock_delay):
        admin_obj = ReportImageAdmin(ReportImage, self.site)

        admin_obj.enqueue_ai_extraction(
            self._build_request(),
            ReportImage.objects.filter(pk=self.image.pk),
        )

        mock_delay.assert_called_once_with(self.image.id)
