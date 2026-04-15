from datetime import date, datetime, timedelta
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase
from django.utils import timezone

from core.models import CheckupLibrary, DailyTask
from core.models.choices import PlanItemCategory, TaskStatus
from health_data.models import (
    AIParseStatus,
    ClinicalEvent,
    HealthMetric,
    MetricType,
    ReportImage,
    ReportUpload,
    UploadSource,
    UploaderRole,
)
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

    def _count_distinct_report_dates_sql(
        self,
        *,
        patient_id: int,
        category_code: str,
        include_deleted: bool = False,
        report_month: str = "",
        start_date=None,
        end_date=None,
    ) -> int:
        clauses = [
            "ru.patient_id = %s",
            "ri.record_type = %s",
            "ri.report_date IS NOT NULL",
            "cl.code = %s",
        ]
        params = [patient_id, int(ReportImage.RecordType.CHECKUP), category_code]

        if not include_deleted:
            clauses.append("ru.deleted_at IS NULL")

        report_month = (report_month or "").strip()
        if report_month:
            month_dt = datetime.strptime(report_month, "%Y-%m")
            month_start = month_dt.date().replace(day=1)
            if month_start.month == 12:
                next_month = month_start.replace(year=month_start.year + 1, month=1, day=1)
            else:
                next_month = month_start.replace(month=month_start.month + 1, day=1)
            month_end = next_month - timedelta(days=1)
            clauses.append("ri.report_date >= %s")
            clauses.append("ri.report_date <= %s")
            params.extend([month_start, month_end])

        if start_date is not None and end_date is not None:
            clauses.append("ri.report_date >= %s")
            clauses.append("ri.report_date <= %s")
            params.extend([start_date, end_date])

        where_sql = " AND ".join(clauses)
        sql = f"""
            SELECT COUNT(DISTINCT ri.report_date)
            FROM health_report_images ri
            JOIN health_report_uploads ru ON ri.upload_id = ru.id
            JOIN core_checkup_library cl ON ri.checkup_item_id = cl.id
            WHERE {where_sql}
        """
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            row = cursor.fetchone()
        return int(row[0] or 0)

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

    def test_create_upload_allows_checkup_without_item_for_plan(self):
        upload = self._create_upload(
            images=[{"image_url": "https://example.com/a.png", "record_type": ReportImage.RecordType.CHECKUP}],
            upload_source=UploadSource.CHECKUP_PLAN,
        )
        image = upload.images.first()
        self.assertEqual(image.record_type, ReportImage.RecordType.CHECKUP)
        self.assertIsNone(image.checkup_item)

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

        # 使用本地日期计算以避免跨时区导致 created_at__date 偏移
        today_local = timezone.localdate()
        base_date = today_local - timedelta(days=2)
        base_time = timezone.make_aware(datetime.combine(base_date, datetime.min.time()))

        ReportUpload.objects.filter(id=upload1.id).update(created_at=base_time)
        ReportUpload.objects.filter(id=upload2.id).update(created_at=base_time + timedelta(days=1))

        qs = ReportUploadService.list_uploads(self.patient, upload_source=UploadSource.CHECKUP_PLAN)
        self.assertEqual(list(qs), [upload2])

        qs = ReportUploadService.list_uploads(
            self.patient,
            start_date=base_date,
            end_date=base_date,
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

    def test_list_report_images_filters_and_ordering(self):
        ReportUploadService.create_upload(
            self.patient,
            images=[
                {
                    "image_url": "https://example.com/nov-14.png",
                    "record_type": ReportImage.RecordType.CHECKUP,
                    "checkup_item_id": self.checkup_item.id,
                    "report_date": date(2025, 11, 14),
                }
            ],
            upload_source=UploadSource.CHECKUP_PLAN,
        )
        ReportUploadService.create_upload(
            self.patient,
            images=[
                {
                    "image_url": "https://example.com/nov-07.png",
                    "record_type": ReportImage.RecordType.CHECKUP,
                    "checkup_item_id": self.checkup_item.id,
                    "report_date": date(2025, 11, 7),
                }
            ],
            upload_source=UploadSource.CHECKUP_PLAN,
        )
        older_upload = ReportUploadService.create_upload(
            self.patient,
            images=[
                {
                    "image_url": "https://example.com/nov-01-deleted.png",
                    "record_type": ReportImage.RecordType.CHECKUP,
                    "checkup_item_id": self.checkup_item.id,
                    "report_date": date(2025, 11, 1),
                }
            ],
            upload_source=UploadSource.CHECKUP_PLAN,
        )
        ReportUpload.objects.filter(id=older_upload.id).update(deleted_at=timezone.now())

        payload = ReportUploadService.list_report_images(
            patient_id=self.patient.id,
            category_code=self.checkup_item.code,
            report_month="2025-11",
            page_num=1,
            page_size=10,
        )
        self.assertEqual(payload["total"], 2)
        self.assertEqual(payload["list"][0]["report_date"], "2025-11-14")
        self.assertEqual(payload["list"][1]["report_date"], "2025-11-07")

        payload_with_deleted = ReportUploadService.list_report_images(
            patient_id=self.patient.id,
            category_code=self.checkup_item.code,
            report_month="2025-11",
            page_num=1,
            page_size=10,
            include_deleted=True,
        )
        self.assertEqual(payload_with_deleted["total"], 3)

    def test_list_report_images_pagination(self):
        ReportUploadService.create_upload(
            self.patient,
            images=[
                {
                    "image_url": "https://example.com/nov-14.png",
                    "record_type": ReportImage.RecordType.CHECKUP,
                    "checkup_item_id": self.checkup_item.id,
                    "report_date": date(2025, 11, 14),
                }
            ],
            upload_source=UploadSource.CHECKUP_PLAN,
        )
        ReportUploadService.create_upload(
            self.patient,
            images=[
                {
                    "image_url": "https://example.com/nov-07.png",
                    "record_type": ReportImage.RecordType.CHECKUP,
                    "checkup_item_id": self.checkup_item.id,
                    "report_date": date(2025, 11, 7),
                }
            ],
            upload_source=UploadSource.CHECKUP_PLAN,
        )

        page1 = ReportUploadService.list_report_images(
            patient_id=self.patient.id,
            category_code=self.checkup_item.code,
            report_month="2025-11",
            page_num=1,
            page_size=1,
        )
        page2 = ReportUploadService.list_report_images(
            patient_id=self.patient.id,
            category_code=self.checkup_item.code,
            report_month="2025-11",
            page_num=2,
            page_size=1,
        )

        self.assertEqual(page1["total"], 2)
        self.assertEqual(page2["total"], 2)
        self.assertEqual(page1["list"][0]["report_date"], "2025-11-14")
        self.assertEqual(page2["list"][0]["report_date"], "2025-11-07")

    def test_list_report_images_grouped_filters_month_and_category(self):
        upload = ReportUploadService.create_upload(
            self.patient,
            images=[
                {
                    "image_url": "https://example.com/nov-14-a.png",
                    "record_type": ReportImage.RecordType.CHECKUP,
                    "checkup_item_id": self.checkup_item.id,
                    "report_date": date(2025, 11, 14),
                },
                {
                    "image_url": "https://example.com/nov-14-b.png",
                    "record_type": ReportImage.RecordType.CHECKUP,
                    "checkup_item_id": self.checkup_item.id,
                    "report_date": date(2025, 11, 14),
                },
            ],
            upload_source=UploadSource.CHECKUP_PLAN,
        )
        self.assertIsNotNone(upload.id)

        ReportUploadService.create_upload(
            self.patient,
            images=[
                {
                    "image_url": "https://example.com/nov-07.png",
                    "record_type": ReportImage.RecordType.CHECKUP,
                    "checkup_item_id": self.checkup_item.id,
                    "report_date": date(2025, 11, 7),
                }
            ],
            upload_source=UploadSource.CHECKUP_PLAN,
        )
        ReportUploadService.create_upload(
            self.patient,
            images=[
                {
                    "image_url": "https://example.com/oct-01.png",
                    "record_type": ReportImage.RecordType.CHECKUP,
                    "checkup_item_id": self.checkup_item.id,
                    "report_date": date(2025, 10, 1),
                }
            ],
            upload_source=UploadSource.CHECKUP_PLAN,
        )

        payload = ReportUploadService.list_report_images(
            patient_id=self.patient.id,
            category_code=self.checkup_item.code,
            report_month="2025-11",
            page_num=1,
            page_size=10,
        )
        self.assertEqual(payload["total"], 2)
        self.assertEqual(len(payload["list"]), 2)
        self.assertEqual(payload["list"][0]["report_date"], "2025-11-14")
        self.assertEqual(len(payload["list"][0]["image_urls"]), 2)
        self.assertEqual(payload["list"][1]["report_date"], "2025-11-07")

    def test_list_report_images_grouped_pagination_by_date(self):
        ReportUploadService.create_upload(
            self.patient,
            images=[
                {
                    "image_url": "https://example.com/nov-14.png",
                    "record_type": ReportImage.RecordType.CHECKUP,
                    "checkup_item_id": self.checkup_item.id,
                    "report_date": date(2025, 11, 14),
                }
            ],
            upload_source=UploadSource.CHECKUP_PLAN,
        )
        ReportUploadService.create_upload(
            self.patient,
            images=[
                {
                    "image_url": "https://example.com/nov-07.png",
                    "record_type": ReportImage.RecordType.CHECKUP,
                    "checkup_item_id": self.checkup_item.id,
                    "report_date": date(2025, 11, 7),
                }
            ],
            upload_source=UploadSource.CHECKUP_PLAN,
        )

        page1 = ReportUploadService.list_report_images(
            patient_id=self.patient.id,
            category_code=self.checkup_item.code,
            report_month="2025-11",
            page_num=1,
            page_size=1,
        )
        page2 = ReportUploadService.list_report_images(
            patient_id=self.patient.id,
            category_code=self.checkup_item.code,
            report_month="2025-11",
            page_num=2,
            page_size=1,
        )
        self.assertEqual(page1["total"], 2)
        self.assertEqual(page2["total"], 2)
        self.assertEqual(page1["list"][0]["report_date"], "2025-11-14")
        self.assertEqual(page2["list"][0]["report_date"], "2025-11-07")

    def test_list_report_images_date_filter_double_none(self):
        ReportUploadService.create_upload(
            self.patient,
            images=[
                {
                    "image_url": "https://example.com/a.png",
                    "record_type": ReportImage.RecordType.CHECKUP,
                    "checkup_item_id": self.checkup_item.id,
                    "report_date": date(2024, 12, 31),
                },
                {
                    "image_url": "https://example.com/b.png",
                    "record_type": ReportImage.RecordType.CHECKUP,
                    "checkup_item_id": self.checkup_item.id,
                    "report_date": date(2025, 1, 1),
                },
            ],
            upload_source=UploadSource.CHECKUP_PLAN,
        )

        payload = ReportUploadService.list_report_images(
            patient_id=self.patient.id,
            category_code=self.checkup_item.code,
            report_month="",
            page_num=1,
            page_size=10,
            start_date=None,
            end_date=None,
        )
        expected = self._count_distinct_report_dates_sql(
            patient_id=self.patient.id,
            category_code=self.checkup_item.code,
            report_month="",
            start_date=None,
            end_date=None,
        )
        self.assertEqual(payload["total"], expected)

    def test_list_report_images_date_filter_only_start_date(self):
        ReportUploadService.create_upload(
            self.patient,
            images=[
                {
                    "image_url": "https://example.com/a.png",
                    "record_type": ReportImage.RecordType.CHECKUP,
                    "checkup_item_id": self.checkup_item.id,
                    "report_date": date(2025, 1, 1),
                },
                {
                    "image_url": "https://example.com/b.png",
                    "record_type": ReportImage.RecordType.CHECKUP,
                    "checkup_item_id": self.checkup_item.id,
                    "report_date": date(2025, 1, 10),
                },
            ],
            upload_source=UploadSource.CHECKUP_PLAN,
        )

        payload = ReportUploadService.list_report_images(
            patient_id=self.patient.id,
            category_code=self.checkup_item.code,
            report_month="",
            page_num=1,
            page_size=10,
            start_date=date(2025, 1, 5),
            end_date=None,
        )
        expected = self._count_distinct_report_dates_sql(
            patient_id=self.patient.id,
            category_code=self.checkup_item.code,
            report_month="",
            start_date=date(2025, 1, 5),
            end_date=None,
        )
        self.assertEqual(payload["total"], expected)

    def test_list_report_images_date_filter_only_end_date(self):
        ReportUploadService.create_upload(
            self.patient,
            images=[
                {
                    "image_url": "https://example.com/a.png",
                    "record_type": ReportImage.RecordType.CHECKUP,
                    "checkup_item_id": self.checkup_item.id,
                    "report_date": date(2025, 1, 1),
                },
                {
                    "image_url": "https://example.com/b.png",
                    "record_type": ReportImage.RecordType.CHECKUP,
                    "checkup_item_id": self.checkup_item.id,
                    "report_date": date(2025, 1, 10),
                },
            ],
            upload_source=UploadSource.CHECKUP_PLAN,
        )

        payload = ReportUploadService.list_report_images(
            patient_id=self.patient.id,
            category_code=self.checkup_item.code,
            report_month="",
            page_num=1,
            page_size=10,
            start_date=None,
            end_date=date(2025, 1, 5),
        )
        expected = self._count_distinct_report_dates_sql(
            patient_id=self.patient.id,
            category_code=self.checkup_item.code,
            report_month="",
            start_date=None,
            end_date=date(2025, 1, 5),
        )
        self.assertEqual(payload["total"], expected)

    def test_list_report_images_date_filter_normal_range(self):
        ReportUploadService.create_upload(
            self.patient,
            images=[
                {
                    "image_url": "https://example.com/a.png",
                    "record_type": ReportImage.RecordType.CHECKUP,
                    "checkup_item_id": self.checkup_item.id,
                    "report_date": date(2025, 1, 1),
                },
                {
                    "image_url": "https://example.com/b.png",
                    "record_type": ReportImage.RecordType.CHECKUP,
                    "checkup_item_id": self.checkup_item.id,
                    "report_date": date(2025, 1, 10),
                },
            ],
            upload_source=UploadSource.CHECKUP_PLAN,
        )

        payload = ReportUploadService.list_report_images(
            patient_id=self.patient.id,
            category_code=self.checkup_item.code,
            report_month="",
            page_num=1,
            page_size=10,
            start_date=date(2025, 1, 5),
            end_date=date(2025, 1, 20),
        )
        expected = self._count_distinct_report_dates_sql(
            patient_id=self.patient.id,
            category_code=self.checkup_item.code,
            report_month="",
            start_date=date(2025, 1, 5),
            end_date=date(2025, 1, 20),
        )
        self.assertEqual(payload["total"], expected)

    def test_list_report_images_date_filter_reverse_range(self):
        ReportUploadService.create_upload(
            self.patient,
            images=[
                {
                    "image_url": "https://example.com/a.png",
                    "record_type": ReportImage.RecordType.CHECKUP,
                    "checkup_item_id": self.checkup_item.id,
                    "report_date": date(2025, 1, 10),
                }
            ],
            upload_source=UploadSource.CHECKUP_PLAN,
        )

        payload = ReportUploadService.list_report_images(
            patient_id=self.patient.id,
            category_code=self.checkup_item.code,
            report_month="",
            page_num=1,
            page_size=10,
            start_date=date(2025, 1, 10),
            end_date=date(2025, 1, 1),
        )
        expected = self._count_distinct_report_dates_sql(
            patient_id=self.patient.id,
            category_code=self.checkup_item.code,
            report_month="",
            start_date=date(2025, 1, 10),
            end_date=date(2025, 1, 1),
        )
        self.assertEqual(payload["total"], expected)

    def test_list_report_images_date_filter_cross_year_range(self):
        ReportUploadService.create_upload(
            self.patient,
            images=[
                {
                    "image_url": "https://example.com/a.png",
                    "record_type": ReportImage.RecordType.CHECKUP,
                    "checkup_item_id": self.checkup_item.id,
                    "report_date": date(2024, 12, 31),
                },
                {
                    "image_url": "https://example.com/b.png",
                    "record_type": ReportImage.RecordType.CHECKUP,
                    "checkup_item_id": self.checkup_item.id,
                    "report_date": date(2025, 1, 1),
                },
            ],
            upload_source=UploadSource.CHECKUP_PLAN,
        )

        payload = ReportUploadService.list_report_images(
            patient_id=self.patient.id,
            category_code=self.checkup_item.code,
            report_month="",
            page_num=1,
            page_size=10,
            start_date=date(2024, 12, 30),
            end_date=date(2025, 1, 2),
        )
        expected = self._count_distinct_report_dates_sql(
            patient_id=self.patient.id,
            category_code=self.checkup_item.code,
            report_month="",
            start_date=date(2024, 12, 30),
            end_date=date(2025, 1, 2),
        )
        self.assertEqual(payload["total"], expected)

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
        event = ClinicalEvent.objects.get(id=images[0].clinical_event_id)
        self.assertEqual(event.archiver_name, self.doctor_profile.name)

    @patch("ai_vision.tasks.extract_report_image_task.delay")
    def test_archive_images_enqueues_ai_parse_and_sets_pending(self, mock_delay):
        upload = self._create_upload(images=["https://example.com/a.png"])
        image = upload.images.first()
        updates = [
            {
                "image_id": image.id,
                "record_type": ReportImage.RecordType.OUTPATIENT,
                "report_date": date(2025, 2, 1),
            }
        ]

        with self.captureOnCommitCallbacks(execute=True):
            updated = ReportArchiveService.archive_images(self.doctor_profile, updates)

        self.assertEqual(updated, 1)
        mock_delay.assert_called_once_with(image.id)
        image.refresh_from_db()
        self.assertEqual(image.ai_parse_status, AIParseStatus.PENDING)
        self.assertEqual(image.ai_error_message, "")
        self.assertIsNone(image.ai_parsed_at)

    @patch("ai_vision.tasks.extract_report_image_task.delay")
    def test_archive_images_does_not_reenqueue_successful_ai_parse(self, mock_delay):
        upload = self._create_upload(images=["https://example.com/a.png"])
        image = upload.images.first()
        image.ai_parse_status = AIParseStatus.SUCCESS
        image.ai_structured_json = {"is_medical_report": True, "items": []}
        image.ai_error_message = ""
        image.save(update_fields=["ai_parse_status", "ai_structured_json", "ai_error_message"])
        updates = [
            {
                "image_id": image.id,
                "record_type": ReportImage.RecordType.OUTPATIENT,
                "report_date": date(2025, 2, 1),
            }
        ]

        with self.captureOnCommitCallbacks(execute=True):
            updated = ReportArchiveService.archive_images(self.doctor_profile, updates)

        self.assertEqual(updated, 1)
        mock_delay.assert_not_called()
        image.refresh_from_db()
        self.assertEqual(image.ai_parse_status, AIParseStatus.SUCCESS)
        self.assertEqual(image.ai_structured_json, {"is_medical_report": True, "items": []})

    @patch("ai_vision.tasks.extract_report_image_task.delay")
    def test_archive_images_reenqueues_failed_ai_parse(self, mock_delay):
        upload = self._create_upload(images=["https://example.com/a.png"])
        image = upload.images.first()
        image.ai_parse_status = AIParseStatus.FAILED
        image.ai_error_message = "old error"
        image.ai_parsed_at = timezone.now()
        image.save(update_fields=["ai_parse_status", "ai_error_message", "ai_parsed_at"])
        updates = [
            {
                "image_id": image.id,
                "record_type": ReportImage.RecordType.OUTPATIENT,
                "report_date": date(2025, 2, 1),
            }
        ]

        with self.captureOnCommitCallbacks(execute=True):
            updated = ReportArchiveService.archive_images(self.doctor_profile, updates)

        self.assertEqual(updated, 1)
        mock_delay.assert_called_once_with(image.id)
        image.refresh_from_db()
        self.assertEqual(image.ai_parse_status, AIParseStatus.PENDING)
        self.assertEqual(image.ai_error_message, "")
        self.assertIsNone(image.ai_parsed_at)

    @patch("ai_vision.tasks.extract_report_image_task.delay", side_effect=RuntimeError("redis down"))
    def test_archive_images_marks_failed_when_task_submit_fails(self, mock_delay):
        upload = self._create_upload(images=["https://example.com/a.png"])
        image = upload.images.first()
        updates = [
            {
                "image_id": image.id,
                "record_type": ReportImage.RecordType.OUTPATIENT,
                "report_date": date(2025, 2, 1),
            }
        ]

        with self.captureOnCommitCallbacks(execute=True):
            updated = ReportArchiveService.archive_images(self.doctor_profile, updates)

        self.assertEqual(updated, 1)
        mock_delay.assert_called_once_with(image.id)
        image.refresh_from_db()
        self.assertEqual(image.ai_parse_status, AIParseStatus.FAILED)
        self.assertIn("AI任务提交失败", image.ai_error_message)
        self.assertIn("redis down", image.ai_error_message)
        self.assertIsNotNone(image.ai_parsed_at)

    def test_archive_images_creates_checkup_metric_and_matches_task(self):
        upload = self._create_upload(images=["https://example.com/a.png"])
        image = upload.images.first()
        report_date = timezone.localdate()
        task = DailyTask.objects.create(
            patient=self.patient,
            task_date=report_date - timedelta(days=1),
            task_type=PlanItemCategory.CHECKUP,
            title="血常规",
            status=TaskStatus.PENDING,
            interaction_payload={"checkup_id": self.checkup_item.id},
        )
        updates = [
            {
                "image_id": image.id,
                "record_type": ReportImage.RecordType.CHECKUP,
                "report_date": report_date,
                "checkup_item_id": self.checkup_item.id,
            }
        ]
        updated = ReportArchiveService.archive_images(self.doctor_profile, updates)
        self.assertEqual(updated, 1)

        metric = HealthMetric.objects.filter(
            patient=self.patient, metric_type=MetricType.CHECKUP
        ).first()
        self.assertIsNotNone(metric)
        self.assertEqual(metric.task_id, task.id)

        image.refresh_from_db()
        self.assertEqual(image.health_metric_id, metric.id)

        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertEqual(task.interaction_payload.get("health_metric_id"), metric.id)

    def test_archive_images_sets_archiver_name(self):
        upload = self._create_upload(images=["https://example.com/a.png"])
        image = upload.images.first()
        updates = [
            {
                "image_id": image.id,
                "record_type": ReportImage.RecordType.OUTPATIENT,
                "report_date": date(2025, 2, 1),
            }
        ]
        updated = ReportArchiveService.archive_images(
            self.doctor_profile,
            updates,
            archiver_name="小桃妖",
        )
        self.assertEqual(updated, 1)
        image.refresh_from_db()
        self.assertIsNotNone(image.clinical_event_id)
        event = ClinicalEvent.objects.get(id=image.clinical_event_id)
        self.assertEqual(event.archiver_name, "小桃妖")

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
        metric = HealthMetric.objects.filter(
            patient=self.patient, metric_type=MetricType.CHECKUP
        ).first()
        self.assertIsNotNone(metric)
        self.assertIsNone(metric.task_id)
        self.assertTrue(images.filter(health_metric=metric).exists())

    def test_create_record_with_images_matches_task(self):
        report_date = timezone.localdate()
        task = DailyTask.objects.create(
            patient=self.patient,
            task_date=report_date,
            task_type=PlanItemCategory.CHECKUP,
            title="血常规",
            status=TaskStatus.PENDING,
            interaction_payload={"checkup_id": self.checkup_item.id},
        )
        event = ReportArchiveService.create_record_with_images(
            patient=self.patient,
            created_by_doctor=self.doctor_profile,
            event_type=ReportImage.RecordType.CHECKUP,
            event_date=report_date,
            images=[
                {"image_url": "https://example.com/a.png", "checkup_item_id": self.checkup_item.id},
                {"image_url": "https://example.com/b.png", "checkup_item_id": self.checkup_item.id},
            ],
        )
        images = ReportImage.objects.filter(clinical_event=event)
        metric = HealthMetric.objects.filter(
            patient=self.patient, metric_type=MetricType.CHECKUP
        ).first()
        self.assertIsNotNone(metric)
        self.assertEqual(metric.task_id, task.id)
        self.assertTrue(images.filter(health_metric=metric).exists())

        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertEqual(task.interaction_payload.get("health_metric_id"), metric.id)

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
