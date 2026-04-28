import json
import re
from datetime import date
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.template.loader import render_to_string
from django.test import TestCase, RequestFactory, SimpleTestCase
from django.urls import reverse

from core.models import CheckupLibrary
from health_data.models import ClinicalEvent, ReportImage, ReportUpload, UploadSource
from users import choices
from users.models import DoctorProfile, PatientProfile


User = get_user_model()


class ConsultationRecordEditTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

        self.doctor_user = User.objects.create_user(
            username="doctor_edit",
            password="password",
            user_type=choices.UserType.DOCTOR,
            phone="13800000002",
        )
        self.doctor = DoctorProfile.objects.create(user=self.doctor_user, name="Test Doctor")

        self.patient_user = User.objects.create_user(
            username="patient_edit",
            user_type=choices.UserType.PATIENT,
            wx_openid="test_openid_edit",
        )
        self.patient = PatientProfile.objects.create(user=self.patient_user, name="Test Patient")

        self.checkup_other = CheckupLibrary.objects.create(name="其他", code="OTHER")
        self.checkup_a = CheckupLibrary.objects.create(name="血常规", code="BLOOD_ROUTINE")
        self.checkup_b = CheckupLibrary.objects.create(name="胸部CT", code="CT_CHEST")

    def _render_record_detail_template(self, report):
        html = render_to_string(
            "web_doctor/partials/reports_history/_record_detail.html",
            {
                "patient": self.patient,
                "report": report,
                "checkup_subcategories": ["血常规", "胸部CT", "其他"],
                "request": self.factory.get("/"),
                "csrf_token": "testtoken",
            },
        )
        return html

    def test_button_state_bindings_exist(self):
        html = self._render_record_detail_template(
            {
                "id": 1,
                "date": date(2025, 1, 1),
                "images": [{"id": 11, "url": "http://test/1.jpg", "thumbnail_url": "http://test/1.jpg", "category": "门诊"}],
                "image_count": 1,
                "interpretation": "",
                "record_type": "门诊",
                "sub_category": "",
                "archiver": "A",
                "archived_date": "2025-01-01",
                "uploader_info": {"name": "U"},
            }
        )
        self.assertIn("x-text=\"editing ? '保存' : '编辑'\"", html)
        self.assertIn("@click=\"cancelEdit($root)\"", html)
        self.assertIn("x-show=\"editing\"", html)
        self.assertNotIn("\\\"", html)

    def test_category_ui_non_checkup_has_no_subcategory_select(self):
        html = self._render_record_detail_template(
            {
                "id": 2,
                "date": date(2025, 1, 2),
                "images": [{"id": 21, "url": "http://test/2.jpg", "thumbnail_url": "http://test/2.jpg", "category": "住院"}],
                "image_count": 1,
                "interpretation": "",
                "record_type": "住院",
                "sub_category": "",
                "archiver": "A",
                "archived_date": "2025-01-02",
                "uploader_info": {"name": "U"},
            }
        )
        self.assertIsNone(re.search(r"<select[^>]*data-subcategory-select", html))
        self.assertIn("value=\"住院\"", html)

    def test_category_ui_checkup_renders_subcategory_select(self):
        html = self._render_record_detail_template(
            {
                "id": 3,
                "date": date(2025, 1, 3),
                "images": [{"id": 31, "url": "http://test/3.jpg", "thumbnail_url": "http://test/3.jpg", "category": "复查-血常规"}],
                "image_count": 1,
                "interpretation": "",
                "record_type": "复查",
                "sub_category": "血常规",
                "archiver": "A",
                "archived_date": "2025-01-03",
                "uploader_info": {"name": "U"},
            }
        )
        self.assertIsNotNone(re.search(r"<select[^>]*data-subcategory-select", html))
        self.assertIn("value=\"复查-血常规\"", html)

    def test_save_edit_integration_updates_interpretation_and_checkup_item(self):
        event = ClinicalEvent.objects.create(
            patient=self.patient,
            event_type=3,
            event_date=date(2025, 1, 5),
            created_by_doctor=self.doctor,
            interpretation="old",
        )
        upload = ReportUpload.objects.create(patient=self.patient, upload_source=UploadSource.DOCTOR_BACKEND)
        img = ReportImage.objects.create(
            upload=upload,
            image_url="http://test.com/edit.jpg",
            record_type=3,
            checkup_item=self.checkup_a,
            clinical_event=event,
            report_date=event.event_date,
            archived_by=self.doctor,
        )

        self.client.force_login(self.doctor_user)
        url = reverse("web_doctor:patient_report_update", args=[self.patient.id, event.id])
        payload = {
            "interpretation": "new interpretation",
            "record_type": "复查",
            "image_updates": [{"image_id": img.id, "category": "复查-胸部CT"}],
        }
        resp = self.client.post(url, data=json.dumps(payload), content_type="application/json")
        self.assertEqual(resp.status_code, 200)

        event.refresh_from_db()
        img.refresh_from_db()
        self.assertEqual(event.interpretation, "new interpretation")
        self.assertEqual(img.checkup_item_id, self.checkup_b.id)

    def test_service_calls_are_used_and_payload_shape_correct(self):
        event = ClinicalEvent.objects.create(
            patient=self.patient,
            event_type=3,
            event_date=date(2025, 1, 6),
            created_by_doctor=self.doctor,
            interpretation="old",
        )
        upload = ReportUpload.objects.create(patient=self.patient, upload_source=UploadSource.DOCTOR_BACKEND)
        img = ReportImage.objects.create(
            upload=upload,
            image_url="http://test.com/edit2.jpg",
            record_type=3,
            checkup_item=self.checkup_a,
            clinical_event=event,
            report_date=event.event_date,
        )

        self.client.force_login(self.doctor_user)
        url = reverse("web_doctor:patient_report_update", args=[self.patient.id, event.id])
        payload = {
            "interpretation": "new",
            "record_type": "复查",
            "image_updates": [{"image_id": img.id, "category": "复查-血常规"}],
        }

        with patch("web_doctor.views.reports_history_data.ReportArchiveService.update_clinical_event") as mock_update, patch(
            "web_doctor.views.reports_history_data.ReportArchiveService.archive_images"
        ) as mock_archive:
            mock_update.side_effect = lambda e, **kwargs: e
            mock_archive.return_value = 1
            resp = self.client.post(url, data=json.dumps(payload), content_type="application/json")

        self.assertEqual(resp.status_code, 200)
        mock_update.assert_called()
        called_event = mock_update.call_args[0][0]
        self.assertEqual(called_event.id, event.id)
        self.assertEqual(mock_update.call_args[1].get("interpretation"), "new")

        self.assertTrue(mock_archive.called)
        archive_args = mock_archive.call_args[0]
        self.assertEqual(archive_args[0].id, self.doctor.id)
        updates = list(archive_args[1])
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["image_id"], img.id)
        self.assertEqual(updates[0]["record_type"], 3)
        self.assertEqual(updates[0]["report_date"], date(2025, 1, 6))
        self.assertEqual(updates[0]["checkup_item_id"], self.checkup_a.id)

    def test_save_edit_validation_error_returns_400(self):
        event = ClinicalEvent.objects.create(
            patient=self.patient,
            event_type=3,
            event_date=date(2025, 1, 7),
            created_by_doctor=self.doctor,
        )
        upload = ReportUpload.objects.create(patient=self.patient, upload_source=UploadSource.DOCTOR_BACKEND)
        img = ReportImage.objects.create(
            upload=upload,
            image_url="http://test.com/edit3.jpg",
            record_type=3,
            clinical_event=event,
            report_date=event.event_date,
        )

        self.client.force_login(self.doctor_user)
        url = reverse("web_doctor:patient_report_update", args=[self.patient.id, event.id])
        payload = {
            "interpretation": "x",
            "record_type": "复查",
            "image_updates": [{"image_id": img.id, "category": "复查-不存在的二级"}],
        }

        with patch("web_doctor.views.reports_history_data.ReportArchiveService.archive_images") as mock_archive:
            from django.core.exceptions import ValidationError

            mock_archive.side_effect = ValidationError("复查项目不存在。")
            resp = self.client.post(url, data=json.dumps(payload), content_type="application/json")

        self.assertEqual(resp.status_code, 400)
        self.assertIn("复查项目不存在", resp.content.decode("utf-8"))

    def test_edit_interpretation_only_does_not_archive_images(self):
        event = ClinicalEvent.objects.create(
            patient=self.patient,
            event_type=3,
            event_date=date(2025, 1, 8),
            created_by_doctor=self.doctor,
            interpretation="old",
        )
        upload = ReportUpload.objects.create(patient=self.patient, upload_source=UploadSource.DOCTOR_BACKEND)
        img = ReportImage.objects.create(
            upload=upload,
            image_url="http://test.com/edit4.jpg",
            record_type=3,
            checkup_item=self.checkup_a,
            clinical_event=event,
            report_date=event.event_date,
        )

        self.client.force_login(self.doctor_user)
        url = reverse("web_doctor:patient_report_update", args=[self.patient.id, event.id])
        payload = {
            "interpretation": "only change interpretation",
            "record_type": "复查",
            "image_updates": [],
        }

        with patch("web_doctor.views.reports_history_data.ReportArchiveService.archive_images") as mock_archive:
            resp = self.client.post(url, data=json.dumps(payload), content_type="application/json")

        self.assertEqual(resp.status_code, 200)
        event.refresh_from_db()
        self.assertEqual(event.interpretation, "only change interpretation")
        mock_archive.assert_not_called()
        img.refresh_from_db()
        self.assertEqual(img.checkup_item_id, self.checkup_a.id)


class ConsultationModalLayeringTemplateTests(SimpleTestCase):
    def _read(self, relative_path: str) -> str:
        return (Path(settings.BASE_DIR) / relative_path).read_text(encoding="utf-8")

    def test_add_record_modal_teleports_to_body(self):
        content = self._read("templates/web_doctor/partials/reports_history/add_record_modal.html")
        self.assertIn("<template x-teleport=\"body\">", content)
        self.assertIn("class=\"fixed inset-0 z-[9999] bg-gray-500 bg-opacity-75 transition-opacity\"", content)
        self.assertIn("class=\"fixed inset-0 z-[10000] w-screen overflow-y-auto\"", content)
        self.assertIn("x-show=\"showRecordTypePrompt\"", content)
        self.assertIn("class=\"fixed inset-0 z-[10001]\"", content)
        self.assertIn("x-cloak", content)

    def test_consultation_delete_modal_teleports_to_body_without_inline_zindex(self):
        content = self._read("templates/web_doctor/partials/reports_history/list.html")
        self.assertIn("<template x-teleport=\"body\">", content)
        self.assertIn("id=\"consultation-delete-modal\" class=\"fixed inset-0 hidden z-[10000] bg-black/50\"", content)
        self.assertNotIn("style=\"background: rgba(0,0,0,0.5);z-index: 9999;\"", content)

    def test_reports_preview_modal_teleports_to_body(self):
        content = self._read("templates/web_doctor/partials/reports_history/list.html")
        self.assertIn("<template x-teleport=\"body\">", content)
        self.assertIn("x-show=\"showPreview\"", content)
        self.assertIn("class=\"fixed inset-0 z-[10000] flex items-center justify-center bg-black/80 backdrop-blur-sm p-4\"", content)
        self.assertIn("@show-preview.window=\"if ($root.contains($event.target)) openPreview($event.detail)\"", content)
        self.assertIn("@close-preview.window=\"closePreview()\"", content)
        self.assertIn("@click.self=\"requestClosePreview()\"", content)
        self.assertIn("@keydown.escape.window=\"requestClosePreview()\"", content)
        self.assertIn("@pointerdown.stop.prevent=\"requestClosePreview()\"", content)
        self.assertIn("aria-label=\"关闭图片预览\"", content)
        self.assertNotIn("@click.outside=\"showPreview = false\"", content)

    def test_home_checkup_modal_teleports_to_body(self):
        content = self._read("templates/web_doctor/partials/home/checkup_record_modal.html")
        self.assertIn("<template x-teleport=\"body\">", content)
        self.assertIn("class=\"fixed inset-0 z-[9999] bg-gray-500 bg-opacity-75 transition-opacity\"", content)
        self.assertIn("class=\"fixed inset-0 z-[10000] w-screen overflow-y-auto\"", content)
        self.assertIn("x-show=\"showRecordTypePrompt\"", content)
        self.assertIn("class=\"fixed inset-0 z-[10001]\"", content)
        self.assertIn("x-cloak", content)

    def test_home_reports_preview_modal_teleports_to_body(self):
        content = self._read("templates/web_doctor/partials/home/reports.html")
        self.assertIn("<template x-teleport=\"body\">", content)
        self.assertIn("x-show=\"showPreview\"", content)
        self.assertIn("class=\"fixed inset-0 z-[10000] flex items-center justify-center bg-black/80 backdrop-blur-sm p-4\"", content)
