from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from market.models import Order, Product
from users.models import DoctorProfile, PatientProfile

User = get_user_model()


class MobilePatientHomeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="doc_mobile_home",
            password="password",
            user_type=2,
            phone="13900139003",
        )
        self.doctor_profile = DoctorProfile.objects.create(user=self.user, name="Dr. Mobile Home")
        self.user.doctor_profile = self.doctor_profile
        self.user.save()

        self.other_user = User.objects.create_user(
            username="doc_mobile_home_other",
            password="password",
            user_type=2,
            phone="13900139004",
        )
        self.other_doctor = DoctorProfile.objects.create(user=self.other_user, name="Dr. Other")
        self.other_user.doctor_profile = self.other_doctor
        self.other_user.save()

        self.product = Product.objects.create(
            name="VIP 监护服务",
            price=Decimal("199.00"),
            duration_days=30,
            is_active=True,
        )

        self.patient_active = PatientProfile.objects.create(
            name="张三",
            phone="13800138201",
            doctor=self.doctor_profile,
        )
        self.patient_unmanaged = PatientProfile.objects.create(
            name="李四",
            phone="13800138202",
            doctor=self.doctor_profile,
        )
        self.patient_other = PatientProfile.objects.create(
            name="赵六",
            phone="13800138203",
            doctor=self.other_doctor,
        )

        Order.objects.create(
            patient=self.patient_active,
            product=self.product,
            amount=Decimal("199.00"),
            status=Order.Status.PAID,
            paid_at=timezone.now() - timedelta(days=1),
        )

    @patch("web_doctor.views.workspace.TodoListService")
    @patch("web_doctor.views.workspace.ChatService")
    def test_mobile_patient_list_items_have_click_payload_fields(self, MockChatService, MockTodoListService):
        mock_page = MagicMock()
        mock_page.paginator.count = 0
        MockTodoListService.get_todo_page.return_value = mock_page

        chat_service = MockChatService.return_value
        chat_service.get_or_create_patient_conversation.return_value = MagicMock()
        chat_service.get_unread_count.return_value = 0

        self.client.force_login(self.user)
        url = reverse("web_doctor:mobile_patient_list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        content = response.content.decode("utf-8")
        self.assertIn(reverse("web_doctor:mobile_patient_home", args=[self.patient_active.id]), content)
        self.assertIn(f'data-patient-id="{self.patient_active.id}"', content)
        self.assertIn(f'data-patient-name="{self.patient_active.name}"', content)
        self.assertIn('data-patient-gender="', content)
        self.assertIn('data-patient-age="', content)

    def test_mobile_patient_home_renders(self):
        self.client.force_login(self.user)
        url = reverse("web_doctor:mobile_patient_home", args=[self.patient_active.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "web_doctor/mobile/patient_home.html")
        content = response.content.decode("utf-8")
        self.assertIn(self.patient_active.name, content)
        self.assertIn(f"P{self.patient_active.id:06d}", content)

    def test_mobile_patient_home_denies_unrelated_patient(self):
        self.client.force_login(self.user)
        url = reverse("web_doctor:mobile_patient_home", args=[self.patient_other.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_mobile_patient_section_placeholder_renders(self):
        self.client.force_login(self.user)
        url = reverse("web_doctor:mobile_patient_section", args=[self.patient_active.id, "todo"])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "web_doctor/mobile/patient_section_placeholder.html")
        content = response.content.decode("utf-8")
        self.assertIn("患者待办", content)

