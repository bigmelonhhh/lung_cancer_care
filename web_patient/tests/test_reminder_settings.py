from django.test import Client, TestCase
from django.urls import reverse

from users import choices
from users.models import CustomUser, PatientProfile


class ReminderSettingsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = CustomUser.objects.create_user(
            username="testpatient_reminder_settings",
            password="password",
            user_type=choices.UserType.PATIENT,
            wx_openid="test_openid_reminder_settings",
            is_subscribe=True,
        )
        self.patient = PatientProfile.objects.create(
            user=self.user,
            name="Test Patient",
            phone="13800000077",
        )
        self.client.force_login(self.user)

    def test_reminder_settings_get_defaults_on(self):
        resp = self.client.get(reverse("web_patient:reminder_settings"))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["is_receive_wechat_message"])
        self.assertTrue(resp.context["is_receive_watch_message"])

    def test_reminder_settings_post_updates_flags(self):
        url = reverse("web_patient:reminder_settings")

        resp = self.client.post(url, data={})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], url)

        self.user.refresh_from_db()
        self.assertFalse(self.user.is_receive_wechat_message)
        self.assertFalse(self.user.is_receive_watch_message)

        resp = self.client.post(
            url,
            data={
                "is_receive_wechat_message": "on",
                "is_receive_watch_message": "on",
            },
        )
        self.assertEqual(resp.status_code, 302)

        self.user.refresh_from_db()
        self.assertTrue(self.user.is_receive_wechat_message)
        self.assertTrue(self.user.is_receive_watch_message)

