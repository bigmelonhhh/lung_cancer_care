from datetime import date

from django.contrib.admin.sites import AdminSite
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase

from core.admin.checkup import CheckupFieldMappingInline, CheckupLibraryAdmin
from core.admin.standard_field import (
    CheckupFieldMappingInlineForField,
    StandardFieldAdmin,
    StandardFieldAliasAdmin,
    StandardFieldAliasInline,
)
from core.models import (
    CheckupFieldMapping,
    CheckupLibrary,
    StandardField,
    StandardFieldAlias,
    StandardFieldValueType,
)
from health_data.admin import CheckupOrphanFieldAdmin
from health_data.models import (
    CheckupOrphanField,
    CheckupResultValue,
    OrphanFieldStatus,
    ReportImage,
    ReportUpload,
)
from users.models import CustomUser, PatientProfile


class StructuredCheckupAdminTests(TestCase):
    def setUp(self):
        self.alias_name = "白细胞后台测试项"
        self.normalized_alias_name = self.alias_name
        self.site = AdminSite()
        self.factory = RequestFactory()
        self.admin_user = CustomUser.objects.create_superuser(
            username="structured_admin",
            password="strong-pass-123",
            phone="13900002000",
        )
        self.patient = PatientProfile.objects.create(phone="13900002001", name="Admin患者")
        self.checkup = CheckupLibrary.objects.create(name="血常规", code="BLOOD_ROUTINE")
        self.field = StandardField.objects.create(
            local_code="WBC_ADMIN_TEST",
            english_abbr="WBC-ADMIN",
            chinese_name="白细胞计数后台测试",
            value_type=StandardFieldValueType.DECIMAL,
            default_unit="10^9/L",
        )
        self.upload = ReportUpload.objects.create(patient=self.patient)
        self.report_image = ReportImage.objects.create(
            upload=self.upload,
            image_url="https://example.com/admin-blood.png",
            record_type=ReportImage.RecordType.CHECKUP,
            checkup_item=self.checkup,
            report_date=date(2026, 4, 2),
        )

    def _build_request(self):
        request = self.factory.post("/admin/")
        SessionMiddleware(lambda req: None).process_request(request)
        request.session.save()
        request.user = self.admin_user
        request._messages = FallbackStorage(request)
        return request

    def test_standard_field_and_checkup_admin_expose_expected_inlines(self):
        standard_admin = StandardFieldAdmin(StandardField, self.site)
        checkup_admin = CheckupLibraryAdmin(CheckupLibrary, self.site)

        self.assertEqual(standard_admin.inlines, [StandardFieldAliasInline, CheckupFieldMappingInlineForField])
        self.assertEqual(checkup_admin.inlines, [CheckupFieldMappingInline])

    def test_alias_admin_action_reprocesses_related_orphans(self):
        orphan = CheckupOrphanField.objects.create(
            patient=self.patient,
            report_image=self.report_image,
            checkup_item=self.checkup,
            report_date=self.report_image.report_date,
            raw_name=self.alias_name,
            normalized_name=self.normalized_alias_name,
            raw_value="5.6",
        )
        alias = StandardFieldAlias.objects.create(
            standard_field=self.field,
            alias_name=self.alias_name,
        )
        CheckupFieldMapping.objects.create(checkup_item=self.checkup, standard_field=self.field)

        admin_obj = StandardFieldAliasAdmin(StandardFieldAlias, self.site)
        admin_obj.reprocess_related_orphans(
            self._build_request(),
            StandardFieldAlias.objects.filter(pk=alias.pk),
        )

        orphan.refresh_from_db()
        self.assertEqual(orphan.status, OrphanFieldStatus.RESOLVED)
        self.assertTrue(
            CheckupResultValue.objects.filter(
                report_image=self.report_image,
                standard_field=self.field,
            ).exists()
        )

    def test_orphan_admin_actions_retry_and_ignore(self):
        pending_orphan = CheckupOrphanField.objects.create(
            patient=self.patient,
            report_image=self.report_image,
            checkup_item=self.checkup,
            report_date=self.report_image.report_date,
            raw_name=self.alias_name,
            normalized_name=self.normalized_alias_name,
            raw_value="5.6",
        )
        ignored_orphan = CheckupOrphanField.objects.create(
            patient=self.patient,
            report_image=self.report_image,
            checkup_item=self.checkup,
            report_date=self.report_image.report_date,
            raw_name="血小板后台测试项",
            normalized_name="血小板后台测试项",
            raw_value="200",
        )

        StandardFieldAlias.objects.create(
            standard_field=self.field,
            alias_name=self.alias_name,
        )
        CheckupFieldMapping.objects.create(checkup_item=self.checkup, standard_field=self.field)

        admin_obj = CheckupOrphanFieldAdmin(CheckupOrphanField, self.site)
        admin_obj.retry_matching(
            self._build_request(),
            CheckupOrphanField.objects.filter(pk=pending_orphan.pk),
        )
        pending_orphan.refresh_from_db()
        self.assertEqual(pending_orphan.status, OrphanFieldStatus.RESOLVED)

        admin_obj.mark_ignored(
            self._build_request(),
            CheckupOrphanField.objects.filter(pk=ignored_orphan.pk),
        )
        ignored_orphan.refresh_from_db()
        self.assertEqual(ignored_orphan.status, OrphanFieldStatus.IGNORED)
