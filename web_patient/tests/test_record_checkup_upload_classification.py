from datetime import date, datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from core.models import CheckupLibrary, DailyTask, choices as core_choices
from health_data.models import ReportImage, ReportUpload
from health_data.models.report_upload import UploadSource, UploaderRole
from users import choices
from users.models import PatientProfile
from health_data.services.report_service import ReportUploadService


User = get_user_model()


class RecordCheckupUploadClassificationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="patient_e2e",
            user_type=choices.UserType.PATIENT,
            wx_openid="openid_e2e",
        )
        self.patient = PatientProfile.objects.create(user=self.user, name="E2E Patient")
        self.today = date(2025, 3, 1)
        self.now = timezone.make_aware(datetime(2025, 3, 1, 9, 0, 0))

        self.lib_blood = CheckupLibrary.objects.create(name="血常规", code="BLOOD_ROUTINE_CODE", is_active=True)
        self.lib_ct = CheckupLibrary.objects.create(name="胸部CT", code="CT_CHEST_CODE", is_active=True)

        self.task_blood = DailyTask.objects.create(
            patient=self.patient,
            task_date=self.today,
            task_type=core_choices.PlanItemCategory.CHECKUP,
            title="复查-血常规",
            interaction_payload={"checkup_id": self.lib_blood.id},
        )
        self.task_ct = DailyTask.objects.create(
            patient=self.patient,
            task_date=self.today,
            task_type=core_choices.PlanItemCategory.CHECKUP,
            title="复查-胸部CT",
            interaction_payload={"checkup_id": self.lib_ct.id},
        )

    def _save_mock_file(self, path: str) -> str:
        saved = default_storage.save(path, ContentFile(b"data"))
        return default_storage.url(saved)

    def test_upload_images_with_checkup_item_id_per_task(self):
        url1 = self._save_mock_file(f"checkup_reports/{self.patient.id}/{self.today}/a.jpg")
        url2 = self._save_mock_file(f"checkup_reports/{self.patient.id}/{self.today}/b.jpg")
        images = [
            {"image_url": url1, "record_type": ReportImage.RecordType.CHECKUP, "report_date": self.today, "checkup_item_id": self.lib_blood.id},
            {"image_url": url2, "record_type": ReportImage.RecordType.CHECKUP, "report_date": self.today, "checkup_item_id": self.lib_ct.id},
        ]

        upload = ReportUploadService.create_upload(
            patient=self.patient,
            images=images,
            uploader=self.user,
            upload_source=UploadSource.CHECKUP_PLAN,
            uploader_role=UploaderRole.PATIENT,
        )
        ReportUpload.objects.filter(id=upload.id).update(created_at=self.now)
        upload.refresh_from_db()

        imgs = ReportImage.objects.filter(upload=upload).order_by("id")
        self.assertEqual(imgs.count(), 2)
        self.assertEqual(imgs[0].checkup_item_id, self.lib_blood.id)
        self.assertEqual(imgs[1].checkup_item_id, self.lib_ct.id)

    def test_doctor_archives_shows_full_category_after_patient_upload(self):
        url1 = self._save_mock_file(f"checkup_reports/{self.patient.id}/{self.today}/c.jpg")
        url2 = self._save_mock_file(f"checkup_reports/{self.patient.id}/{self.today}/d.jpg")
        images = [
            {"image_url": url1, "record_type": ReportImage.RecordType.CHECKUP, "report_date": self.today, "checkup_item_id": self.lib_blood.id},
            {"image_url": url2, "record_type": ReportImage.RecordType.CHECKUP, "report_date": self.today, "checkup_item_id": self.lib_ct.id},
        ]
        upload = ReportUploadService.create_upload(
            patient=self.patient,
            images=images,
            uploader=self.user,
            upload_source=UploadSource.CHECKUP_PLAN,
            uploader_role=UploaderRole.PATIENT,
        )
        ReportUpload.objects.filter(id=upload.id).update(created_at=self.now)
        upload.refresh_from_db()

        from web_doctor.views.reports_history_data import _get_archives_data
        archives_list, _page_obj = _get_archives_data(self.patient, page=1, page_size=10)
        images_out = []
        for group in archives_list:
            images_out.extend(group["images"])
        cats = {img["category"] for img in images_out}
        self.assertIn("复查-血常规", cats)
        self.assertIn("复查-胸部CT", cats)
