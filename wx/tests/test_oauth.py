from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from wx.services.oauth import generate_menu_auth_url, get_oauth_url


class OAuthUrlTests(SimpleTestCase):
    @override_settings(DEBUG=True, TEST_PATIENT_ID="7", WEB_BASE_URL="http://example.com")
    def test_generate_menu_auth_url_uses_oauth_in_test_mode(self):
        with patch("wx.services.oauth.get_oauth_url", return_value="AUTH_URL") as mock_get_oauth_url:
            url = generate_menu_auth_url(
                "web_patient:bind_landing",
                patient_id=1,
                state="bind_patient_1",
            )

        self.assertEqual(url, "AUTH_URL")
        mock_get_oauth_url.assert_called_once_with(
            "http://example.com/p/bind/1/",
            scope="snsapi_base",
            state="bind_patient_1",
        )

    def test_get_oauth_url_passes_scope_and_state(self):
        mock_client = type("MockOAuthClient", (), {"authorize_url": "AUTH_URL"})()

        with patch("wx.services.oauth._get_wechat_o_auth_cliet", return_value=mock_client) as mock_factory:
            url = get_oauth_url(
                "http://example.com/p/bind/1/",
                scope="snsapi_userinfo",
                state="bind_patient_1",
            )

        self.assertEqual(url, "AUTH_URL")
        mock_factory.assert_called_once_with(
            "http://example.com/p/bind/1/",
            scope="snsapi_userinfo",
            state="bind_patient_1",
        )
