from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from chat.models import Conversation, ConversationType, Message, MessageSenderRole
from users.choices import UserType
from users.models import AssistantProfile, DoctorAssistantMap, DoctorProfile, DoctorStudio, PatientProfile

User = get_user_model()


class ListMessagesPermissionRegressionTest(TestCase):
    def setUp(self):
        self.client = Client()

        self.director_user = User.objects.create_user(
            username="director_perm_reg",
            password="password",
            user_type=UserType.DOCTOR,
            phone="13900139101",
        )
        self.director_profile = DoctorProfile.objects.create(user=self.director_user, name="Director Perm")
        self.studio_a = DoctorStudio.objects.create(name="Studio A", code="STU_A", owner_doctor=self.director_profile)
        self.director_profile.studio = self.studio_a
        self.director_profile.save()

        self.other_owner_user = User.objects.create_user(
            username="owner_b",
            password="password",
            user_type=UserType.DOCTOR,
            phone="13900139102",
        )
        self.other_owner_profile = DoctorProfile.objects.create(user=self.other_owner_user, name="Owner B")
        self.studio_b = DoctorStudio.objects.create(name="Studio B", code="STU_B", owner_doctor=self.other_owner_profile)
        self.other_owner_profile.studio = self.studio_b
        self.other_owner_profile.save()

        self.platform_user = User.objects.create_user(
            username="platform_perm_reg",
            password="password",
            user_type=UserType.DOCTOR,
            phone="13900139103",
        )
        self.platform_profile = DoctorProfile.objects.create(user=self.platform_user, name="Platform Perm")
        self.platform_profile.studio = self.studio_a
        self.platform_profile.save()

        self.patient_user = User.objects.create_user(
            username="patient_perm_reg",
            password="password",
            user_type=UserType.PATIENT,
            phone="13900139104",
            wx_openid="test_openid_perm_reg_1",
        )
        self.patient = PatientProfile.objects.create(
            user=self.patient_user,
            name="Patient Perm",
            phone="13900139104",
            doctor=self.platform_profile,
            is_active=True,
        )

        self.conversation = Conversation.objects.create(
            type=ConversationType.PATIENT_STUDIO,
            patient=self.patient,
            studio=self.studio_b,
            created_by=self.director_user,
        )
        Message.objects.create(
            conversation=self.conversation,
            sender=self.patient_user,
            sender_role_snapshot=MessageSenderRole.PATIENT,
            sender_display_name_snapshot="患者",
            studio_name_snapshot=self.studio_b.name,
            text_content="hello",
        )

        self.url = reverse("web_doctor:chat_api_list_messages")

    def test_director_can_view_patient_conversation_even_if_conversation_studio_mismatch(self):
        self.client.force_login(self.director_user)
        response = self.client.get(self.url, {"conversation_id": self.conversation.id})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(len(payload["messages"]), 1)

    def test_assistant_can_view_patient_conversation_even_if_conversation_studio_mismatch(self):
        assistant_user = User.objects.create_user(
            username="assistant_perm_reg",
            password="password",
            user_type=UserType.ASSISTANT,
            phone="13900139105",
        )
        assistant_profile = AssistantProfile.objects.create(user=assistant_user, name="Asst Perm")
        DoctorAssistantMap.objects.create(doctor=self.platform_profile, assistant=assistant_profile)

        self.client.force_login(assistant_user)
        response = self.client.get(self.url, {"conversation_id": self.conversation.id})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")

    def test_unrelated_doctor_is_denied(self):
        unrelated_user = User.objects.create_user(
            username="unrelated_perm_reg",
            password="password",
            user_type=UserType.DOCTOR,
            phone="13900139106",
        )
        unrelated_profile = DoctorProfile.objects.create(user=unrelated_user, name="Unrelated")
        unrelated_studio = DoctorStudio.objects.create(name="Studio C", code="STU_C", owner_doctor=unrelated_profile)
        unrelated_profile.studio = unrelated_studio
        unrelated_profile.save()

        self.client.force_login(unrelated_user)
        response = self.client.get(self.url, {"conversation_id": self.conversation.id})
        self.assertEqual(response.status_code, 403)
