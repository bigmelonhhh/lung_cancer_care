from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase
from django.urls import reverse

from health_data.models import ClinicalEvent, ReportImage, ReportUpload, UploadSource
from users import choices
from users.models import DoctorProfile, PatientProfile
from web_doctor.views.reports_history_data import handle_reports_history_section


User = get_user_model()


class ReportsHistoryFragmentTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.doctor_user = User.objects.create_user(
            username="doctor_reports_fragments",
            password="password",
            user_type=choices.UserType.DOCTOR,
            phone="13800000999",
        )
        self.doctor = DoctorProfile.objects.create(user=self.doctor_user, name="Dr. Fragment")
        self.patient_user = User.objects.create_user(
            username="patient_reports_fragments",
            user_type=choices.UserType.PATIENT,
            wx_openid="openid_reports_fragments",
        )
        self.patient = PatientProfile.objects.create(user=self.patient_user, name="Patient Fragment", doctor=self.doctor)

    def test_records_tab_only_builds_records_context(self):
        request = self.factory.get("/?tab=records")
        request.user = self.doctor_user

        with patch("web_doctor.views.reports_history_data.get_reports_page_for_patient") as mock_reports, patch(
            "web_doctor.views.reports_history_data._get_archives_data"
        ) as mock_archives:
            mock_reports.return_value = type("Obj", (), {"object_list": [], "paginator": type("P", (), {"num_pages": 1})()})()
            template_name = handle_reports_history_section(request, {"patient": self.patient})

        self.assertEqual(template_name, "web_doctor/partials/reports_history/list.html")
        mock_reports.assert_called_once()
        mock_archives.assert_not_called()

    def test_images_tab_only_builds_archive_context(self):
        request = self.factory.get("/?tab=images")
        request.user = self.doctor_user

        with patch("web_doctor.views.reports_history_data.get_reports_page_for_patient") as mock_reports, patch(
            "web_doctor.views.reports_history_data._get_archives_data"
        ) as mock_archives:
            mock_archives.return_value = ([], type("Obj", (), {"paginator": type("P", (), {"num_pages": 1})(), "number": 1})())
            template_name = handle_reports_history_section(request, {"patient": self.patient})

        self.assertEqual(template_name, "web_doctor/partials/reports_history/list.html")
        mock_archives.assert_called_once()
        mock_reports.assert_not_called()

    def test_records_initial_html_does_not_render_detail_images_or_add_modal(self):
        reports_page = type(
            "Page",
            (),
            {
                "paginator": type("P", (), {"num_pages": 1})(),
                "__iter__": lambda self: iter(
                    [
                        {
                            "id": 1,
                            "date": date(2025, 1, 1),
                            "images": [{"id": 10, "url": "http://test/hidden.jpg"}],
                            "image_count": 1,
                            "interpretation": "hidden",
                            "record_type": "门诊",
                            "sub_category": "",
                            "archiver": "Dr. Fragment",
                            "archived_date": "2025-01-01",
                            "uploader_info": {"name": "Uploader"},
                        }
                    ]
                ),
            },
        )()

        html = render_to_string(
            "web_doctor/partials/reports_history/consultation_records.html",
            {
                "patient": self.patient,
                "reports_page": reports_page,
                "filters": {
                    "recordType": "",
                    "reportDateStart": "",
                    "reportDateEnd": "",
                    "archivedDateStart": "",
                    "archivedDateEnd": "",
                    "archiver": "",
                },
                "request": self.factory.get("/"),
            },
        )

        self.assertNotIn("http://test/hidden.jpg", html)
        self.assertNotIn("新增诊疗记录", html)
        self.assertIn("report-detail-body-1", html)

    def test_report_update_returns_summary_and_detail_fragments(self):
        event = ClinicalEvent.objects.create(
            patient=self.patient,
            event_type=1,
            event_date=date(2025, 1, 2),
            created_by_doctor=self.doctor,
            interpretation="before",
        )
        upload = ReportUpload.objects.create(patient=self.patient, upload_source=UploadSource.DOCTOR_BACKEND)
        ReportImage.objects.create(
            upload=upload,
            image_url="http://test/update.jpg",
            record_type=1,
            clinical_event=event,
            report_date=event.event_date,
            archived_by=self.doctor,
        )

        self.client.force_login(self.doctor_user)
        response = self.client.post(
            reverse("web_doctor:patient_report_update", args=[self.patient.id, event.id]),
            data='{"record_type":"门诊","interpretation":"after","image_updates":[]}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("summary_html", payload)
        self.assertIn("detail_html", payload)
        self.assertIn("保存成功", payload["message"])
        self.assertIn("report-row-summary-", payload["summary_html"])
        self.assertIn("报告备注与解读", payload["detail_html"])
