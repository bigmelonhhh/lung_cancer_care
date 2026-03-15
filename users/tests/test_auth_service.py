from django.test import TestCase

from users.services.auth import AuthService


class AuthServiceTests(TestCase):
    def setUp(self) -> None:
        self.service = AuthService()

    def test_get_or_create_wechat_user_uses_full_openid_for_username(self):
        first_openid = "o0SRd60uAAAA11112222333344445555"
        second_openid = "o0SRd60uBBBB11112222333344445555"

        first_user, first_created = self.service.get_or_create_wechat_user(first_openid)
        second_user, second_created = self.service.get_or_create_wechat_user(second_openid)

        self.assertTrue(first_created)
        self.assertTrue(second_created)
        self.assertEqual(first_user.username, f"wx_{first_openid}")
        self.assertEqual(second_user.username, f"wx_{second_openid}")
        self.assertNotEqual(first_user.username, second_user.username)

    def test_get_or_create_wechat_user_returns_existing_user(self):
        openid = "o0SRd60uCCCC11112222333344445555"

        first_user, first_created = self.service.get_or_create_wechat_user(openid)
        second_user, second_created = self.service.get_or_create_wechat_user(openid)

        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(first_user.id, second_user.id)
