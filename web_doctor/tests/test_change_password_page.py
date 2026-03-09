from django.test import TestCase
from django.urls import reverse

from users import choices
from users.models import CustomUser


class DoctorChangePasswordPageTests(TestCase):
    def setUp(self):
        self.doctor = CustomUser.objects.create_user(
            username="doctor_change_pwd_ui",
            password="password123",
            phone="13800009901",
            user_type=choices.UserType.DOCTOR,
        )
        self.url = reverse("web_doctor:doctor_change_password")

    def test_change_password_page_contains_core_ui_elements(self):
        self.client.force_login(self.doctor)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "web_doctor/change_password.html")
        self.assertContains(response, "医生工作室 · 修改密码")
        self.assertContains(response, "更新登录密码")
        self.assertContains(response, 'name="old_password"', html=False)
        self.assertContains(response, 'name="new_password1"', html=False)
        self.assertContains(response, 'name="new_password2"', html=False)
        self.assertContains(response, "保存密码")
