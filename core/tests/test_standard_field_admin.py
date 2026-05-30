from datetime import date
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.forms.models import inlineformset_factory
from django.test import RequestFactory, TestCase

from core.admin.checkup import CheckupFieldMappingInline, CheckupLibraryAdmin
from core.admin.standard_field import (
    CheckupFieldMappingInlineForField,
    StandardFieldAdmin,
    StandardFieldAdminForm,
    StandardFieldAliasAdmin,
    StandardFieldAliasAdminForm,
    StandardFieldAliasInlineFormSet,
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

    def _standard_field_form_data(self, **overrides):
        data = {
            "local_code": "NEW_STANDARD_FIELD_ADMIN_TEST",
            "english_abbr": "NEW-ADMIN",
            "chinese_name": "新增后台标准字段",
            "value_type": StandardFieldValueType.DECIMAL,
            "default_unit": "mg/L",
            "description": "",
            "is_active": "on",
            "sort_order": "0",
        }
        data.update(overrides)
        return data

    def test_standard_field_and_checkup_admin_expose_expected_inlines(self):
        standard_admin = StandardFieldAdmin(StandardField, self.site)
        checkup_admin = CheckupLibraryAdmin(CheckupLibrary, self.site)

        self.assertEqual(standard_admin.inlines, [StandardFieldAliasInline, CheckupFieldMappingInlineForField])
        self.assertEqual(checkup_admin.inlines, [CheckupFieldMappingInline])

    def test_standard_field_admin_form_rejects_duplicate_normalized_chinese_name(self):
        StandardField.objects.create(
            local_code="CRP_ADMIN_DUP",
            english_abbr="CRP-DUP",
            chinese_name="C反应蛋白",
            value_type=StandardFieldValueType.DECIMAL,
            default_unit="mg/L",
        )

        form = StandardFieldAdminForm(
            data=self._standard_field_form_data(
                local_code="CRP_ARISTO_ADMIN_DUP",
                chinese_name="C反应蛋白(Aristo检测)",
            )
        )

        self.assertFalse(form.is_valid())
        self.assertIn("归一化后名称“C反应蛋白”已存在", form.errors["chinese_name"][0])
        self.assertIn("已有标准字段“C反应蛋白（CRP_ADMIN_DUP）”", form.errors["chinese_name"][0])

    def test_standard_field_admin_form_rejects_alias_owned_by_other_field(self):
        StandardFieldAlias.objects.create(
            standard_field=self.field,
            alias_name="人工白细胞",
        )

        form = StandardFieldAdminForm(
            data=self._standard_field_form_data(
                local_code="AI_WBC_ADMIN_DUP",
                chinese_name="人工白细胞(门诊)",
            )
        )

        self.assertFalse(form.is_valid())
        self.assertIn("已有别名“人工白细胞”对应标准字段", form.errors["chinese_name"][0])

    def test_standard_field_admin_form_allows_own_alias_on_edit(self):
        StandardFieldAlias.objects.create(
            standard_field=self.field,
            alias_name=self.alias_name,
        )

        form = StandardFieldAdminForm(
            data=self._standard_field_form_data(
                local_code=self.field.local_code,
                english_abbr=self.field.english_abbr,
                chinese_name=self.alias_name,
                default_unit=self.field.default_unit,
                sort_order=str(self.field.sort_order),
            ),
            instance=self.field,
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_alias_admin_form_rejects_duplicate_normalized_name(self):
        StandardFieldAlias.objects.create(
            standard_field=self.field,
            alias_name="后台归一化重复别名",
        )

        form = StandardFieldAliasAdminForm(
            data={
                "standard_field": str(self.field.pk),
                "alias_name": "后台归一化重复别名(Aristo检测)",
                "is_active": "on",
                "notes": "",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("归一化后名称“后台归一化重复别名”已存在", form.errors["alias_name"][0])

    def test_alias_admin_form_reports_existing_alias_for_parenthetical_formula(self):
        existing_alias = StandardFieldAlias.objects.select_related("standard_field").get(normalized_name="EGFR")

        form = StandardFieldAliasAdminForm(
            data={
                "standard_field": str(self.field.pk),
                "alias_name": "eGFR(CKD-EPI)",
                "is_active": "on",
                "notes": "",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn(
            f"已有别名“{existing_alias.alias_name}”对应标准字段"
            f"“{existing_alias.standard_field.chinese_name}（{existing_alias.standard_field.local_code}）”",
            form.errors["alias_name"][0],
        )

    def test_alias_admin_form_reports_existing_alias_for_parenthetical_vendor_name(self):
        existing_alias = StandardFieldAlias.objects.select_related("standard_field").get(normalized_name="C反应蛋白")

        form = StandardFieldAliasAdminForm(
            data={
                "standard_field": str(self.field.pk),
                "alias_name": "C反应蛋白(Aristo检测)",
                "is_active": "on",
                "notes": "",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("归一化后名称“C反应蛋白”已存在", form.errors["alias_name"][0])
        self.assertIn(
            f"已有别名“{existing_alias.alias_name}”对应标准字段"
            f"“{existing_alias.standard_field.chinese_name}（{existing_alias.standard_field.local_code}）”",
            form.errors["alias_name"][0],
        )

    def test_alias_admin_form_reports_existing_alias_for_gamma_symbol_name(self):
        existing_alias = StandardFieldAlias.objects.select_related("standard_field").get(
            normalized_name="谷氨酰转肽酶",
        )

        form = StandardFieldAliasAdminForm(
            data={
                "standard_field": str(self.field.pk),
                "alias_name": "γ-谷氨酰转肽酶",
                "is_active": "on",
                "notes": "",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("归一化后名称“谷氨酰转肽酶”已存在", form.errors["alias_name"][0])
        self.assertIn(f"已有别名“{existing_alias.alias_name}”对应标准字段", form.errors["alias_name"][0])

    def test_alias_admin_form_reports_existing_alias_for_latin_v_name_when_present(self):
        StandardFieldAlias.objects.create(
            standard_field=self.field,
            alias_name="V谷氨酰转肽酶",
        )

        form = StandardFieldAliasAdminForm(
            data={
                "standard_field": str(self.field.pk),
                "alias_name": "V-谷氨酰转肽酶",
                "is_active": "on",
                "notes": "",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("归一化后名称“V谷氨酰转肽酶”已存在", form.errors["alias_name"][0])
        self.assertIn("已有别名“V谷氨酰转肽酶”对应标准字段", form.errors["alias_name"][0])

    def test_alias_admin_form_allows_latin_a_l_when_alpha_l_alias_exists(self):
        self.assertTrue(StandardFieldAlias.objects.filter(normalized_name="L岩藻糖苷酶").exists())

        form = StandardFieldAliasAdminForm(
            data={
                "standard_field": str(self.field.pk),
                "alias_name": "a-L-岩藻糖苷酶",
                "is_active": "on",
                "notes": "",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_alias_admin_form_allows_existing_alias_to_keep_its_name(self):
        alias = StandardFieldAlias.objects.create(
            standard_field=self.field,
            alias_name=self.alias_name,
        )

        form = StandardFieldAliasAdminForm(
            data={
                "standard_field": str(self.field.pk),
                "alias_name": self.alias_name,
                "is_active": "on",
                "notes": "",
            },
            instance=alias,
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_alias_inline_formset_rejects_duplicate_normalized_names_in_same_submission(self):
        formset_class = inlineformset_factory(
            StandardField,
            StandardFieldAlias,
            form=StandardFieldAliasAdminForm,
            formset=StandardFieldAliasInlineFormSet,
            fields=("alias_name", "is_active", "notes"),
            extra=2,
        )
        formset = formset_class(
            data={
                "aliases-TOTAL_FORMS": "2",
                "aliases-INITIAL_FORMS": "0",
                "aliases-MIN_NUM_FORMS": "0",
                "aliases-MAX_NUM_FORMS": "1000",
                "aliases-0-alias_name": "后台内联重复别名(Aristo检测)",
                "aliases-0-is_active": "on",
                "aliases-0-notes": "",
                "aliases-1-alias_name": "后台内联重复别名",
                "aliases-1-is_active": "on",
                "aliases-1-notes": "",
            },
            instance=self.field,
            prefix="aliases",
        )

        self.assertFalse(formset.is_valid())
        self.assertIn("本次提交中存在归一化后重复的别名", formset.non_form_errors()[0])

    @patch("health_data.tasks.reprocess_orphan_fields_task.delay")
    def test_alias_admin_action_reprocesses_related_orphans(self, mock_delay):
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

        mock_delay.assert_called_once_with(normalized_names=[alias.normalized_name])

    @patch("health_data.tasks.reprocess_orphan_fields_task.delay")
    def test_orphan_admin_actions_retry_and_ignore(self, mock_delay):
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
        mock_delay.assert_called_once_with(orphan_ids=[pending_orphan.pk])

        admin_obj.mark_ignored(
            self._build_request(),
            CheckupOrphanField.objects.filter(pk=ignored_orphan.pk),
        )
        ignored_orphan.refresh_from_db()
        self.assertEqual(ignored_orphan.status, OrphanFieldStatus.IGNORED)
