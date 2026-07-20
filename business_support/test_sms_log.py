from unittest.mock import patch

from django.apps import apps
from django.contrib import admin
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, SimpleTestCase, TestCase

from business_support.models import SMSLog
from business_support.service.sms import SMSService
from users.models import CustomUser
from web_patient.views.entry import send_auth_code


class SMSLogModelTests(SimpleTestCase):
    def test_sms_log_exposes_minimum_audit_fields(self):
        model = apps.all_models["business_support"].get("smslog")

        self.assertIsNotNone(model)
        field_names = {field.name for field in model._meta.fields}
        self.assertTrue(
            {"requested_by", "phone", "content", "is_success", "created_at"}
            <= field_names
        )


class SMSServiceLoggingTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create(username="sms_requester")

    @patch("business_support.service.sms.cache.set")
    @patch("business_support.service.sms.cache.ttl", return_value=0)
    @patch.object(SMSService, "_send_api_request", return_value=(True, None))
    def test_successful_send_creates_log_with_full_content(
        self,
        _mock_send,
        _mock_ttl,
        _mock_cache_set,
    ):
        success, message = SMSService.send_verification_code("13800138000")

        self.assertTrue(success)
        self.assertEqual(message, "发送成功")
        log = SMSLog.objects.first()
        self.assertIsNotNone(log)
        self.assertIsNone(log.requested_by)
        self.assertEqual(log.phone, "13800138000")
        self.assertEqual(log.content, _mock_send.call_args.args[1])
        self.assertIn("您的验证码是：", log.content)
        self.assertRegex(log.content, r"\d{4}")
        self.assertTrue(log.is_success)

    @patch("business_support.service.sms.cache.set")
    @patch("business_support.service.sms.cache.ttl", return_value=0)
    @patch.object(SMSService, "_send_api_request", return_value=(True, None))
    def test_send_records_requesting_user(
        self,
        _mock_send,
        _mock_ttl,
        _mock_cache_set,
    ):
        try:
            SMSService.send_verification_code(
                "13800138001",
                requested_by=self.user,
            )
        except TypeError as exc:
            self.fail(f"send_verification_code must accept requested_by: {exc}")

        self.assertEqual(SMSLog.objects.get().requested_by, self.user)

    @patch("business_support.service.sms.cache.ttl", return_value=0)
    @patch.object(
        SMSService,
        "_send_api_request",
        return_value=(False, "供应商错误码: -2"),
    )
    def test_failed_send_creates_unsuccessful_log(self, _mock_send, _mock_ttl):
        success, message = SMSService.send_verification_code("13800138003")

        self.assertFalse(success)
        self.assertEqual(message, "供应商错误码: -2")
        log = SMSLog.objects.get()
        self.assertEqual(log.phone, "13800138003")
        self.assertFalse(log.is_success)


class SMSRequestLoggingTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @patch.object(SMSService, "send_verification_code", return_value=(True, "发送成功"))
    def test_send_code_passes_authenticated_request_user(self, mock_send):
        request = self.factory.post("/p/api/send-code/", {"phone": "13800138002"})
        request.user = type("AuthenticatedUser", (), {"is_authenticated": True})()

        response = send_auth_code(request)

        self.assertEqual(response.status_code, 200)
        mock_send.assert_called_once_with(
            "13800138002",
            requested_by=request.user,
        )

    @patch.object(SMSService, "send_verification_code", return_value=(True, "发送成功"))
    def test_send_code_allows_anonymous_request(self, mock_send):
        request = self.factory.post("/p/api/send-code/", {"phone": "13800138004"})
        request.user = AnonymousUser()

        response = send_auth_code(request)

        self.assertEqual(response.status_code, 200)
        mock_send.assert_called_once_with("13800138004", requested_by=None)


class SMSLogAdminTests(SimpleTestCase):
    def test_sms_log_admin_is_registered_as_read_only(self):
        admin_obj = admin.site._registry.get(SMSLog)

        self.assertIsNotNone(admin_obj)
        request = RequestFactory().get("/admin/business_support/smslog/")
        self.assertFalse(admin_obj.has_add_permission(request))
        self.assertFalse(admin_obj.has_change_permission(request))
        self.assertFalse(admin_obj.has_delete_permission(request))
