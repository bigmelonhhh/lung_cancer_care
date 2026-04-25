from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import CheckupFieldMapping, CheckupLibrary, StandardField, StandardFieldValueType, choices
from users import choices as user_choices
from users.models import AssistantProfile, DoctorProfile, PatientProfile

User = get_user_model()


@patch("web_doctor.views.indicators.get_treatment_cycles", return_value=SimpleNamespace(object_list=[]))
@patch("web_doctor.views.indicators.get_adherence_metrics_batch", return_value=[])
@patch("web_doctor.views.indicators.QuestionnaireSubmissionService.list_daily_questionnaire_scores", return_value=[])
@patch("web_doctor.views.indicators.QuestionnaireSubmissionService.list_daily_cough_hemoptysis_flags", return_value=[])
@patch("web_doctor.views.indicators.HealthMetricService.query_metrics_by_type", return_value=SimpleNamespace(object_list=[]))
class FollowupReviewPreferencesViewTests(TestCase):
    def setUp(self):
        self.doctor_user = User.objects.create_user(
            username="followup_pref_doctor",
            password="password",
            user_type=user_choices.UserType.DOCTOR,
            phone="13900139101",
        )
        self.doctor = DoctorProfile.objects.create(user=self.doctor_user, name="Dr. Followup Pref")
        self.patient = PatientProfile.objects.create(
            name="核心指标配置患者",
            phone="13800139101",
            doctor=self.doctor,
        )
        self.url = reverse("web_doctor:patient_indicator_preferences_update", args=[self.patient.id])

    def _create_mapping(self, *, value_type=StandardFieldValueType.DECIMAL, is_active=True):
        checkup = CheckupLibrary.objects.create(
            name=f"检查项{CheckupLibrary.objects.count()}",
            code=f"CHECKUP_PREF_{CheckupLibrary.objects.count()}",
            category=choices.CheckupCategory.BLOOD,
            is_active=True,
        )
        field = StandardField.objects.create(
            local_code=f"FIELD_PREF_{StandardField.objects.count()}",
            chinese_name=f"指标{StandardField.objects.count()}",
            value_type=value_type,
            is_active=True,
        )
        return CheckupFieldMapping.objects.create(
            checkup_item=checkup,
            standard_field=field,
            is_active=is_active,
        )

    def test_doctor_can_save_patient_level_preferences(self, *_mocks):
        selectable_mapping = self._create_mapping()
        text_mapping = self._create_mapping(value_type=StandardFieldValueType.TEXT)

        self.client.force_login(self.doctor_user)
        response = self.client.post(
            self.url,
            {
                "review_metric_mappings": [
                    str(selectable_mapping.id),
                    "invalid",
                    str(text_mapping.id),
                    str(selectable_mapping.id),
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.patient.refresh_from_db()
        preferences = self.patient.indicator_preferences
        self.assertEqual(preferences["version"], 1)
        self.assertEqual(
            preferences["followup_review"]["selected_mapping_ids"],
            [selectable_mapping.id],
        )
        self.assertEqual(preferences["followup_review"]["updated_by"], self.doctor_user.id)
        self.assertContains(response, 'id="followup-review-section"')
        self.assertContains(response, 'name="review_metric_mappings"')
        self.assertNotContains(response, "常规监测指标")
        self.assertNotContains(response, "随访问卷")
        for mock in _mocks:
            mock.assert_not_called()

    def test_assistant_can_save_for_bound_doctor_patient(self, *_mocks):
        mapping = self._create_mapping()
        assistant_user = User.objects.create_user(
            username="followup_pref_assistant",
            password="password",
            user_type=user_choices.UserType.ASSISTANT,
            phone="13900139102",
        )
        assistant = AssistantProfile.objects.create(user=assistant_user, name="Followup Assistant")
        assistant.doctors.add(self.doctor)

        self.client.force_login(assistant_user)
        response = self.client.post(self.url, {"review_metric_mappings": [str(mapping.id)]})

        self.assertEqual(response.status_code, 200)
        self.patient.refresh_from_db()
        self.assertEqual(
            self.patient.indicator_preferences["followup_review"]["selected_mapping_ids"],
            [mapping.id],
        )

    def test_unmanaged_patient_returns_404(self, *_mocks):
        other_user = User.objects.create_user(
            username="followup_pref_other_doctor",
            password="password",
            user_type=user_choices.UserType.DOCTOR,
            phone="13900139103",
        )
        other_doctor = DoctorProfile.objects.create(user=other_user, name="Dr. Other Pref")
        other_patient = PatientProfile.objects.create(
            name="无权限患者",
            phone="13800139103",
            doctor=other_doctor,
        )

        self.client.force_login(self.doctor_user)
        response = self.client.post(
            reverse("web_doctor:patient_indicator_preferences_update", args=[other_patient.id]),
            {"review_metric_mappings": []},
        )

        self.assertEqual(response.status_code, 404)

    def test_empty_selection_can_be_saved(self, *_mocks):
        mapping = self._create_mapping()
        self.patient.indicator_preferences = {
            "version": 1,
            "followup_review": {"selected_mapping_ids": [mapping.id]},
        }
        self.patient.save(update_fields=["indicator_preferences"])

        self.client.force_login(self.doctor_user)
        response = self.client.post(self.url, {})

        self.assertEqual(response.status_code, 200)
        self.patient.refresh_from_db()
        self.assertEqual(
            self.patient.indicator_preferences["followup_review"]["selected_mapping_ids"],
            [],
        )
        self.assertContains(response, "暂未配置核心关注指标")
