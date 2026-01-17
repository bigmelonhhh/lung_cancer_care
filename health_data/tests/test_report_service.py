from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from core.models import CheckupLibrary
from health_data.models import ClinicalEvent, ReportImage, ReportUpload, UploadSource, UploaderRole
from health_data.services.report_service import ReportArchiveService, ReportUploadService
from users import choices as user_choices
from users.models import CustomUser, DoctorProfile, PatientProfile


class ReportServiceTest(TestCase):
    def setUp(self):
        self.patient_user = CustomUser.objects.create_user(
            user_type=user_choices.UserType.PATIENT,
            wx_openid="wx_patient_001",
        )
        self.patient = PatientProfile.objects.create(
            user=self.patient_user,
            name="患者A",
            phone="13900000001",
        )
        self.doctor_user = CustomUser.objects.create_user(
            user_type=user_choices.UserType.DOCTOR,
            phone="13800000001",
        )
        self.doctor_profile = DoctorProfile.objects.create(
            user=self.doctor_user,
            name="医生A",
            hospital="市一医院",
            department="肿瘤科",
        )
        self.checkup_item = CheckupLibrary.objects.create(
            name="血常规",
            code="BLOOD_ROUTINE",
        )

    def _create_upload(self, **kwargs) -> ReportUpload:
        images = kwargs.pop("images", ["https://example.com/a.png"])
        return ReportUploadService.create_upload(self.patient, images, **kwargs)

    def test_create_upload_basic(self):
        upload = self._create_upload(images=["https://example.com/a.png", "https://example.com/b.png"])
        self.assertEqual(upload.images.count(), 2)
        self.assertEqual(upload.uploader_role, UploaderRole.PATIENT)
        self.assertEqual(upload.upload_source, UploadSource.PERSONAL_CENTER)

    def test_create_upload_with_checkup(self):
        upload = self._create_upload(
            images=[
                {
                    "image_url": "https://example.com/c.png",
                    "record_type": ReportImage.RecordType.CHECKUP,
                    "checkup_item_id": self.checkup_item.id,
                    "report_date": date(2025, 1, 1),
                }
            ],
            uploader=self.doctor_user,
            upload_source=UploadSource.CHECKUP_PLAN,
        )
        image = upload.images.first()
        self.assertEqual(upload.uploader_role, UploaderRole.DOCTOR)
        self.assertEqual(image.record_type, ReportImage.RecordType.CHECKUP)
        self.assertEqual(image.checkup_item, self.checkup_item)
        self.assertEqual(image.report_date, date(2025, 1, 1))

    def test_create_upload_with_record_type(self):
        upload = self._create_upload(
            images=[
                {
                    "image_url": "https://example.com/d.png",
                    "record_type": ReportImage.RecordType.OUTPATIENT,
                    "report_date": date(2025, 1, 18),
                }
            ]
        )
        image = upload.images.first()
        self.assertEqual(image.record_type, ReportImage.RecordType.OUTPATIENT)
        self.assertEqual(image.report_date, date(2025, 1, 18))
        self.assertIsNone(image.checkup_item)

    def test_create_upload_without_record_type(self):
        upload = self._create_upload(images=["https://example.com/e.png"])
        image = upload.images.first()
        self.assertIsNone(image.record_type)
        self.assertIsNone(image.report_date)
        self.assertIsNone(image.checkup_item)

    def test_create_upload_requires_images(self):
        with self.assertRaises(ValidationError):
            ReportUploadService.create_upload(self.patient, [])

    def test_create_upload_requires_checkup_item(self):
        with self.assertRaises(ValidationError):
            self._create_upload(
                images=[{"image_url": "https://example.com/a.png", "record_type": ReportImage.RecordType.CHECKUP}]
            )

    def test_create_upload_rejects_checkup_item_for_non_checkup(self):
        with self.assertRaises(ValidationError):
            self._create_upload(
                images=[
                    {
                        "image_url": "https://example.com/a.png",
                        "record_type": ReportImage.RecordType.OUTPATIENT,
                        "checkup_item_id": self.checkup_item.id,
                    }
                ]
            )

    def test_create_upload_invalid_record_type(self):
        with self.assertRaises(ValidationError):
            self._create_upload(
                images=[{"image_url": "https://example.com/a.png", "record_type": 99}]
            )

    def test_list_uploads_filters(self):
        upload1 = self._create_upload()
        upload2 = self._create_upload(upload_source=UploadSource.CHECKUP_PLAN)

        base_time = timezone.now() - timedelta(days=2)
        ReportUpload.objects.filter(id=upload1.id).update(created_at=base_time)
        ReportUpload.objects.filter(id=upload2.id).update(created_at=base_time + timedelta(days=1))

        qs = ReportUploadService.list_uploads(self.patient, upload_source=UploadSource.CHECKUP_PLAN)
        self.assertEqual(list(qs), [upload2])

        qs = ReportUploadService.list_uploads(
            self.patient,
            start_date=base_time.date(),
            end_date=base_time.date(),
        )
        self.assertEqual(list(qs), [upload1])

    def test_list_uploads_pagination(self):
        upload1 = self._create_upload()
        upload2 = self._create_upload()

        base_time = timezone.now() - timedelta(days=2)
        ReportUpload.objects.filter(id=upload1.id).update(created_at=base_time)
        ReportUpload.objects.filter(id=upload2.id).update(created_at=base_time + timedelta(days=1))

        page1 = ReportUploadService.list_uploads(self.patient, page=1, page_size=1)
        page2 = ReportUploadService.list_uploads(self.patient, page=2, page_size=1)

        self.assertEqual(list(page1), [upload2])
        self.assertEqual(list(page2), [upload1])
        self.assertEqual(page1.paginator.count, 2)

    def test_delete_upload_hard_delete(self):
        upload = self._create_upload(images=["https://example.com/a.png"])
        deleted = ReportUploadService.delete_upload(upload)
        self.assertTrue(deleted)
        self.assertFalse(ReportUpload.objects.filter(id=upload.id).exists())
        self.assertEqual(ReportImage.objects.count(), 0)

    def test_delete_upload_soft_delete(self):
        upload = self._create_upload()
        event = ClinicalEvent.objects.create(
            patient=self.patient,
            event_type=ReportImage.RecordType.OUTPATIENT,
            event_date=date(2025, 1, 1),
            created_by_doctor=self.doctor_profile,
        )
        image = upload.images.first()
        image.clinical_event = event
        image.save(update_fields=["clinical_event"])

        deleted = ReportUploadService.delete_upload(upload)
        upload.refresh_from_db()

        self.assertFalse(deleted)
        self.assertIsNotNone(upload.deleted_at)
        self.assertTrue(upload.images.exists())
        self.assertEqual(
            list(ReportUploadService.list_uploads(self.patient, include_deleted=False)),
            [],
        )
        self.assertEqual(
            list(ReportUploadService.list_uploads(self.patient, include_deleted=True)),
            [upload],
        )

    def test_create_clinical_event_updates_missing_fields(self):
        event_date = date(2025, 1, 1)
        event = ReportArchiveService.create_clinical_event(
            patient=self.patient,
            event_type=ReportImage.RecordType.OUTPATIENT,
            event_date=event_date,
            hospital_name="医院A",
        )
        updated = ReportArchiveService.create_clinical_event(
            patient=self.patient,
            event_type=ReportImage.RecordType.OUTPATIENT,
            event_date=event_date,
            hospital_name="医院B",
            department_name="肿瘤科",
            interpretation="解读",
            created_by_doctor=self.doctor_profile,
        )
        event.refresh_from_db()
        self.assertEqual(event.id, updated.id)
        self.assertEqual(event.hospital_name, "医院A")
        self.assertEqual(event.department_name, "肿瘤科")
        self.assertEqual(event.interpretation, "解读")
        self.assertEqual(event.created_by_doctor, self.doctor_profile)

    def test_create_clinical_event_invalid(self):
        with self.assertRaises(ValidationError):
            ReportArchiveService.create_clinical_event(
                patient=self.patient,
                event_type=99,
                event_date=date(2025, 1, 1),
            )

    def test_update_clinical_event(self):
        event = ClinicalEvent.objects.create(
            patient=self.patient,
            event_type=ReportImage.RecordType.OUTPATIENT,
            event_date=date(2025, 1, 1),
        )
        ReportArchiveService.update_clinical_event(
            event,
            hospital_name="医院A",
            department_name="肿瘤科",
            interpretation="备注",
        )
        event.refresh_from_db()
        self.assertEqual(event.hospital_name, "医院A")
        self.assertEqual(event.department_name, "肿瘤科")
        self.assertEqual(event.interpretation, "备注")

    def test_archive_images_success(self):
        upload = self._create_upload(images=["https://example.com/a.png", "https://example.com/b.png"])
        images = list(upload.images.all())
        updates = [
            {
                "image_id": images[0].id,
                "record_type": ReportImage.RecordType.CHECKUP,
                "report_date": date(2025, 2, 1),
                "checkup_item_id": self.checkup_item.id,
            },
            {
                "image_id": images[1].id,
                "record_type": ReportImage.RecordType.CHECKUP,
                "report_date": date(2025, 2, 1),
                "checkup_item_id": self.checkup_item.id,
            },
        ]
        updated = ReportArchiveService.archive_images(self.doctor_profile, updates)
        self.assertEqual(updated, 2)

        images = list(ReportImage.objects.filter(id__in=[img.id for img in images]).order_by("id"))
        self.assertIsNotNone(images[0].archived_at)
        self.assertEqual(images[0].archived_by, self.doctor_profile)
        self.assertEqual(images[0].clinical_event_id, images[1].clinical_event_id)
        self.assertEqual(images[0].checkup_item, self.checkup_item)

    def test_archive_images_validation(self):
        upload = self._create_upload()
        image = upload.images.first()

        with self.assertRaises(ValidationError):
            ReportArchiveService.archive_images(self.doctor_profile, [])

        with self.assertRaises(ValidationError):
            ReportArchiveService.archive_images(self.doctor_profile, [{"record_type": 1}])

        with self.assertRaises(ValidationError):
            ReportArchiveService.archive_images(
                self.doctor_profile,
                [{"image_id": 9999, "record_type": 1, "report_date": date(2025, 1, 1)}],
            )

        with self.assertRaises(ValidationError):
            ReportArchiveService.archive_images(
                self.doctor_profile,
                [{"image_id": image.id, "record_type": 1, "report_date": None}],
            )

        with self.assertRaises(ValidationError):
            ReportArchiveService.archive_images(
                self.doctor_profile,
                [{"image_id": image.id, "record_type": ReportImage.RecordType.CHECKUP, "report_date": date(2025, 1, 1)}],
            )

        with self.assertRaises(ValidationError):
            ReportArchiveService.archive_images(
                self.doctor_profile,
                [
                    {
                        "image_id": image.id,
                        "record_type": ReportImage.RecordType.OUTPATIENT,
                        "report_date": date(2025, 1, 1),
                        "checkup_item_id": self.checkup_item.id,
                    }
                ],
            )

    def test_create_record_with_images(self):
        event = ReportArchiveService.create_record_with_images(
            patient=self.patient,
            created_by_doctor=self.doctor_profile,
            event_type=ReportImage.RecordType.CHECKUP,
            event_date=date(2025, 3, 1),
            images=[
                {"image_url": "https://example.com/a.png", "checkup_item_id": self.checkup_item.id},
                {"image_url": "https://example.com/b.png", "checkup_item_id": self.checkup_item.id},
            ],
            hospital_name="医院A",
            department_name="肿瘤科",
            interpretation="备注",
        )
        self.assertEqual(event.patient, self.patient)
        self.assertEqual(event.hospital_name, "医院A")
        self.assertEqual(event.interpretation, "备注")

        images = ReportImage.objects.filter(clinical_event=event)
        self.assertEqual(images.count(), 2)
        self.assertTrue(images.filter(archived_by=self.doctor_profile).exists())
        upload = ReportUpload.objects.filter(images__in=images).first()
        self.assertEqual(upload.upload_source, UploadSource.DOCTOR_BACKEND)
        self.assertEqual(upload.uploader_role, UploaderRole.DOCTOR)

    def test_create_record_with_images_requires_checkup_item(self):
        with self.assertRaises(ValidationError):
            ReportArchiveService.create_record_with_images(
                patient=self.patient,
                created_by_doctor=self.doctor_profile,
                event_type=ReportImage.RecordType.CHECKUP,
                event_date=date(2025, 3, 1),
                images=[{"image_url": "https://example.com/a.png"}],
            )

    def test_delete_clinical_event(self):
        event = ReportArchiveService.create_record_with_images(
            patient=self.patient,
            created_by_doctor=self.doctor_profile,
            event_type=ReportImage.RecordType.OUTPATIENT,
            event_date=date(2025, 3, 2),
            images=[{"image_url": "https://example.com/a.png"}],
        )
        images = list(ReportImage.objects.filter(clinical_event=event))
        cleared = ReportArchiveService.delete_clinical_event(event)
        self.assertEqual(cleared, len(images))
        self.assertFalse(ClinicalEvent.objects.filter(id=event.id).exists())
        images[0].refresh_from_db()
        self.assertIsNone(images[0].clinical_event)
        self.assertIsNone(images[0].record_type)
