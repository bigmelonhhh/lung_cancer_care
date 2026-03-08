from types import SimpleNamespace

from django.test import TestCase

from users import choices
from users.models import CustomUser, PatientProfile, PatientRelation
from web_patient.views.chat import _resolve_current_chat_sender_name


class ChatSenderNameTests(TestCase):
    def setUp(self):
        self.patient_user = CustomUser.objects.create_user(
            username="patient_sender_name",
            phone="13870000001",
            user_type=choices.UserType.PATIENT,
            wx_openid="openid_sender_patient",
            wx_nickname="患者微信名",
        )
        self.patient = PatientProfile.objects.create(
            user=self.patient_user,
            name="患者本人姓名",
            phone="13870000001",
        )

        self.family_user = CustomUser.objects.create_user(
            username="family_sender_name",
            phone="13870000002",
            user_type=choices.UserType.PATIENT,
            wx_openid="openid_sender_family",
            wx_nickname="家属微信名",
        )
        PatientRelation.objects.create(
            patient=self.patient,
            user=self.family_user,
            name="家属真实姓名",
            relation_type=choices.RelationType.SPOUSE,
            relation_name="配偶",
            is_active=True,
        )

    def test_patient_login_prefers_patient_profile_name(self):
        request = SimpleNamespace(user=self.patient_user)
        resolved = _resolve_current_chat_sender_name(request, self.patient)
        self.assertEqual(resolved, "患者本人姓名")

    def test_family_login_prefers_relation_name(self):
        request = SimpleNamespace(user=self.family_user)
        resolved = _resolve_current_chat_sender_name(request, self.patient)
        self.assertEqual(resolved, "家属真实姓名")

    def test_family_without_relation_name_falls_back_to_user_display_name(self):
        relation = PatientRelation.objects.get(patient=self.patient, user=self.family_user)
        relation.name = ""
        relation.save(update_fields=["name"])

        request = SimpleNamespace(user=self.family_user)
        resolved = _resolve_current_chat_sender_name(request, self.patient)
        self.assertEqual(resolved, self.family_user.display_name)
