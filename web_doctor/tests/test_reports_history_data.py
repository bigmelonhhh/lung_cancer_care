from datetime import datetime, date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from core.models import CheckupLibrary, DailyTask, choices as core_choices
from health_data.models import ReportImage, ReportUpload
from health_data.models.report_upload import UploadSource
from users import choices
from users.models import PatientProfile
from web_doctor.views.reports_history_data import _get_archives_data


User = get_user_model()


class ReportsHistoryDataArchivesCategoryTests(TestCase):
    def setUp(self):
        self.patient_user = User.objects.create_user(
            username="patient_reports_history_data",
            user_type=choices.UserType.PATIENT,
            wx_openid="openid_reports_history_data",
        )
        self.patient = PatientProfile.objects.create(user=self.patient_user, name="Test Patient")

    def _create_task(self, title: str, payload: dict | None = None):
        return DailyTask.objects.create(
            patient=self.patient,
            task_date=date(2025, 1, 1),
            task_type=core_choices.PlanItemCategory.CHECKUP,
            title=title,
            interaction_payload=payload or {},
        )

    def _create_upload_with_image(
        self,
        *,
        source: int,
        created_at: datetime,
        report_date: date,
        record_type: int,
        checkup_item: CheckupLibrary | None = None,
        related_task: DailyTask | None = None,
    ):
        upload = ReportUpload.objects.create(
            patient=self.patient,
            upload_source=source,
            related_task=related_task,
        )
        ReportUpload.objects.filter(id=upload.id).update(created_at=timezone.make_aware(created_at))
        upload.refresh_from_db()
        ReportImage.objects.create(
            upload=upload,
            image_url=f"http://test/{upload.id}.png",
            record_type=record_type,
            checkup_item=checkup_item,
            report_date=report_date,
        )
        return upload

    def _flatten_images(self, archives_list: list[dict]):
        images = []
        for group in archives_list:
            images.extend(group.get("images") or [])
        return images

    def test_review_plan_upload_returns_full_category_from_checkup_library(self):
        lib_blood = CheckupLibrary.objects.create(name="血常规", code="BLOOD_ROUTINE_TEST", is_active=True)
        lib_special = CheckupLibrary.objects.create(name="生化全项-特殊&%", code="BIOCHEM_SPECIAL_TEST", is_active=True)
        lib_empty = CheckupLibrary.objects.create(name="", code="EMPTY_NAME_TEST", is_active=True)

        task_blood = self._create_task("复查任务-血常规", {"checkup_id": lib_blood.id})
        task_special = self._create_task("复查任务-生化", {"checkup_id": lib_special.id})
        task_missing = self._create_task("", {})
        task_empty_name = self._create_task("空名称", {"checkup_id": lib_empty.id})

        self._create_upload_with_image(
            source=UploadSource.CHECKUP_PLAN,
            created_at=datetime(2025, 1, 1, 10, 0, 0),
            report_date=date(2025, 1, 1),
            record_type=ReportImage.RecordType.CHECKUP,
            checkup_item=None,
            related_task=task_blood,
        )
        self._create_upload_with_image(
            source=UploadSource.CHECKUP_PLAN,
            created_at=datetime(2025, 1, 2, 10, 0, 0),
            report_date=date(2025, 1, 2),
            record_type=ReportImage.RecordType.CHECKUP,
            checkup_item=None,
            related_task=task_special,
        )
        self._create_upload_with_image(
            source=UploadSource.CHECKUP_PLAN,
            created_at=datetime(2025, 1, 3, 10, 0, 0),
            report_date=date(2025, 1, 3),
            record_type=ReportImage.RecordType.CHECKUP,
            checkup_item=None,
            related_task=task_missing,
        )
        self._create_upload_with_image(
            source=UploadSource.CHECKUP_PLAN,
            created_at=datetime(2025, 1, 4, 10, 0, 0),
            report_date=date(2025, 1, 4),
            record_type=ReportImage.RecordType.CHECKUP,
            checkup_item=None,
            related_task=task_empty_name,
        )

        archives_list, _page_obj = _get_archives_data(self.patient, page=1, page_size=10)
        images = self._flatten_images(archives_list)
        images_by_date = {img["report_date"]: img for img in images}

        self.assertEqual(images_by_date["2025-01-01"]["category"], "复查-血常规")
        self.assertEqual(images_by_date["2025-01-01"]["record_type"], "复查")
        self.assertEqual(images_by_date["2025-01-01"]["sub_category"], "血常规")

        self.assertEqual(images_by_date["2025-01-02"]["category"], "复查-生化全项-特殊&%")
        self.assertEqual(images_by_date["2025-01-02"]["sub_category"], "生化全项-特殊&%")

        self.assertEqual(images_by_date["2025-01-03"]["category"], "复查")
        self.assertEqual(images_by_date["2025-01-03"]["sub_category"], "")

        self.assertEqual(images_by_date["2025-01-04"]["category"], "复查")
        self.assertEqual(images_by_date["2025-01-04"]["sub_category"], "")

    def test_non_review_upload_category_is_unchanged(self):
        lib_ct = CheckupLibrary.objects.create(name="胸部CT", code="CT_CHEST_TEST", is_active=True)
        lib_other = CheckupLibrary.objects.create(name="血常规", code="BLOOD_ROUTINE_TEST_2", is_active=True)
        task_blood = self._create_task("复查任务-血常规", {"checkup_id": lib_other.id})

        self._create_upload_with_image(
            source=UploadSource.PERSONAL_CENTER,
            created_at=datetime(2025, 2, 1, 10, 0, 0),
            report_date=date(2025, 2, 1),
            record_type=ReportImage.RecordType.CHECKUP,
            checkup_item=lib_ct,
            related_task=None,
        )
        self._create_upload_with_image(
            source=UploadSource.PERSONAL_CENTER,
            created_at=datetime(2025, 2, 2, 10, 0, 0),
            report_date=date(2025, 2, 2),
            record_type=ReportImage.RecordType.CHECKUP,
            checkup_item=None,
            related_task=None,
        )
        self._create_upload_with_image(
            source=UploadSource.PERSONAL_CENTER,
            created_at=datetime(2025, 2, 3, 10, 0, 0),
            report_date=date(2025, 2, 3),
            record_type=ReportImage.RecordType.CHECKUP,
            checkup_item=None,
            related_task=task_blood,
        )

        archives_list, _page_obj = _get_archives_data(self.patient, page=1, page_size=10)
        images = self._flatten_images(archives_list)
        categories_by_date = {img["report_date"]: img["category"] for img in images}

        self.assertEqual(categories_by_date["2025-02-01"], "复查-胸部CT")
        self.assertEqual(categories_by_date["2025-02-02"], "复查")
        self.assertEqual(categories_by_date["2025-02-03"], "复查")

