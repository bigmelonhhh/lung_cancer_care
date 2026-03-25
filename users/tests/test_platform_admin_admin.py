from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from django.urls import reverse

from users import choices
from users.models import CustomUser, PlatformAdminUser


class PlatformAdminAdminTests(TestCase):
    def setUp(self):
        self.superuser = CustomUser.objects.create_superuser(
            username="root_admin",
            password="admin-pass-123",
            phone="13900000000",
            wx_nickname="Root",
        )
        self.client.force_login(self.superuser)
        self.group = Group.objects.create(name="平台运营组")
        self.permission = (
            Permission.objects.filter(codename="change_customuser").first()
            or Permission.objects.first()
        )
        self.assertIsNotNone(self.permission)
        self.url = reverse("admin:users_platformadminuser_add")

    def test_add_platform_admin_saves_m2m_without_error(self):
        response = self.client.post(
            self.url,
            {
                "username": "platform_admin_a",
                "name": "平台管理员A",
                "phone": "13900000001",
                "password": "strong-pass-123",
                "is_active": "on",
                "is_staff": "on",
                "groups": [str(self.group.pk)],
                "user_permissions": [str(self.permission.pk)],
                "_save": "保存",
            },
        )

        self.assertEqual(response.status_code, 302)

        user = PlatformAdminUser.objects.get(username="platform_admin_a")
        self.assertEqual(user.user_type, choices.UserType.ADMIN)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.groups.filter(pk=self.group.pk).exists())
        self.assertTrue(user.user_permissions.filter(pk=self.permission.pk).exists())
        self.assertTrue(user.check_password("strong-pass-123"))
