from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from users.choices import UserType
from users.models import (
    AssistantProfile,
    DoctorAssistantMap,
    DoctorProfile,
    DoctorStudio,
    PatientProfile,
)

User = get_user_model()


class ChatContextPermissionsTest(TestCase):
    def setUp(self):
        self.director_user = User.objects.create_user(
            username="director_ctx",
            password="password",
            user_type=UserType.DOCTOR,
            phone="13900139011",
        )
        self.director_profile = DoctorProfile.objects.create(user=self.director_user, name="Dr Director")
        self.studio = DoctorStudio.objects.create(name="Ctx Studio", owner_doctor=self.director_profile)
        self.director_profile.studio = self.studio
        self.director_profile.save()

        self.platform_user = User.objects.create_user(
            username="platform_ctx",
            password="password",
            user_type=UserType.DOCTOR,
            phone="13900139012",
        )
        self.platform_profile = DoctorProfile.objects.create(user=self.platform_user, name="Dr Platform")
        self.platform_profile.studio = self.studio
        self.platform_profile.save()

        self.assistant_user = User.objects.create_user(
            username="assistant_ctx",
            password="password",
            user_type=UserType.ASSISTANT,
            phone="13900139013",
        )
        self.assistant_profile = AssistantProfile.objects.create(user=self.assistant_user, name="Asst A")
        DoctorAssistantMap.objects.create(doctor=self.platform_profile, assistant=self.assistant_profile)

        self.patient_user = User.objects.create_user(
            username="patient_ctx",
            password="password",
            user_type=UserType.PATIENT,
            phone="13900139014",
            wx_openid="test_openid_ctx_1",
        )
        self.patient = PatientProfile.objects.create(
            user=self.patient_user,
            name="Patient A",
            phone="13900139014",
            doctor=self.platform_profile,
            is_active=True,
        )

        self.url = reverse("web_doctor:chat_api_get_context")

    def test_director_patient_tab_readonly_internal_writable(self):
        self.client.force_login(self.director_user)
        response = self.client.get(self.url, {"patient_id": self.patient.id})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        data = payload["data"]

        self.assertTrue(data["is_director"])
        self.assertFalse(data["can_send_patient"])
        self.assertTrue(data["can_send_internal"])

    def test_platform_doctor_can_chat_both_tabs(self):
        self.client.force_login(self.platform_user)
        response = self.client.get(self.url, {"patient_id": self.patient.id})
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]

        self.assertFalse(data["is_director"])
        self.assertTrue(data["can_send_patient"])
        self.assertTrue(data["can_send_internal"])

    def test_assistant_can_chat_both_tabs(self):
        self.client.force_login(self.assistant_user)
        response = self.client.get(self.url, {"patient_id": self.patient.id})
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]

        self.assertFalse(data["is_director"])
        self.assertTrue(data["can_send_patient"])
        self.assertTrue(data["can_send_internal"])

