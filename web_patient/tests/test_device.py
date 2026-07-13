import json
from decimal import Decimal
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from business_support.models import Device
from market.models import Order, Product
from users import choices
from users.models import CustomUser, PatientProfile


@override_settings(DEBUG=True, TEST_PATIENT_ID="1")
class DeviceUnbindFlowTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = CustomUser.objects.create_user(
            username="device_unbind_patient",
            password="password",
            user_type=choices.UserType.PATIENT,
            wx_openid="test_openid_device_unbind",
        )
        self.patient = PatientProfile.objects.create(
            user=self.user,
            name="Device Patient",
            phone="13800000004",
        )
        product = Product.objects.create(
            name="设备服务包",
            price=Decimal("199.00"),
            duration_days=30,
            is_active=True,
        )
        Order.objects.create(
            patient=self.patient,
            product=product,
            amount=Decimal("199.00"),
            status=Order.Status.PAID,
            paid_at=timezone.now(),
        )
        self.device = Device.objects.create(
            sn="TEST-DEVICE-SN-001",
            imei="TEST-DEVICE-IMEI-001",
            model_name="Test Watch",
            current_patient=self.patient,
            bind_at=timezone.now(),
        )
        self.client.force_login(self.user)

    @patch("web_patient.views.device._build_wechat_js_config", return_value=None)
    def test_unbind_then_reload_renders_empty_state(self, _build_wechat_js_config):
        response = self.client.post(
            reverse("web_patient:api_unbind_device"),
            data=json.dumps({"imei": self.device.imei}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertEqual(response.json()["status"], "unbound")

        self.device.refresh_from_db()
        self.assertIsNone(self.device.current_patient_id)
        self.assertIsNone(self.device.bind_at)

        response = self.client.get(reverse("web_patient:device_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "暂无绑定设备")
        self.assertContains(response, 'src="/static/images/empty_devices.svg"')

