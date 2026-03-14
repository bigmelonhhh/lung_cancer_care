from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from chat.models import PatientStudioAssignment
from market.models import Order, Product
from users.models import DoctorProfile, DoctorStudio, PatientProfile

User = get_user_model()


class MobilePatientListTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="doc_mobile_patients",
            password="password",
            user_type=2,
            phone="13900139002",
        )
        self.doctor_profile = DoctorProfile.objects.create(user=self.user, name="Dr. Mobile")
        self.user.doctor_profile = self.doctor_profile
        self.user.save()

        self.fallback_director_user = User.objects.create_user(
            username="doc_mobile_fallback_director",
            password="password",
            user_type=2,
            phone="13900139021",
        )
        self.fallback_director = DoctorProfile.objects.create(
            user=self.fallback_director_user,
            name="Dr. Mobile Fallback Director",
        )
        self.fallback_director_user.doctor_profile = self.fallback_director
        self.fallback_director_user.save()

        self.assignment_director_user = User.objects.create_user(
            username="doc_mobile_assignment_director",
            password="password",
            user_type=2,
            phone="13900139022",
        )
        self.assignment_director = DoctorProfile.objects.create(
            user=self.assignment_director_user,
            name="Dr. Mobile Assignment Director",
        )
        self.assignment_director_user.doctor_profile = self.assignment_director
        self.assignment_director_user.save()

        self.fallback_studio = DoctorStudio.objects.create(
            name="移动端兜底工作室",
            code="MOBILE_FALLBACK_001",
            owner_doctor=self.fallback_director,
        )
        self.assignment_studio = DoctorStudio.objects.create(
            name="移动端归属工作室",
            code="MOBILE_ASSIGN_001",
            owner_doctor=self.assignment_director,
        )
        self.doctor_profile.studio = self.fallback_studio
        self.doctor_profile.save(update_fields=["studio"])

        self.product = Product.objects.create(
            name="VIP 监护服务",
            price=Decimal("199.00"),
            duration_days=30,
            is_active=True,
        )

        self.patient_active = PatientProfile.objects.create(
            name="张三",
            phone="13800138101",
            doctor=self.doctor_profile,
        )
        self.patient_expired = PatientProfile.objects.create(
            name="李四",
            phone="13800138102",
            doctor=self.doctor_profile,
        )
        self.patient_none = PatientProfile.objects.create(
            name="赵六",
            phone="13800138103",
            doctor=self.doctor_profile,
        )

        Order.objects.create(
            patient=self.patient_active,
            product=self.product,
            amount=Decimal("199.00"),
            status=Order.Status.PAID,
            paid_at=timezone.now() - timedelta(days=1),
        )
        Order.objects.create(
            patient=self.patient_expired,
            product=self.product,
            amount=Decimal("199.00"),
            status=Order.Status.PAID,
            paid_at=timezone.now() - timedelta(days=60),
        )
        PatientStudioAssignment.objects.create(
            patient=self.patient_active,
            studio=self.assignment_studio,
            start_at=timezone.now() - timedelta(days=2),
        )

    @patch("web_doctor.views.workspace.TodoListService")
    @patch("web_doctor.views.workspace.ChatService")
    def test_mobile_patient_list_renders_and_groups(self, MockChatService, MockTodoListService):
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
        self.assertTemplateUsed(response, "web_doctor/mobile/patient_list.html")

        content = response.content.decode("utf-8")
        self.assertIn("管理中患者", content)
        self.assertIn("未管理的患者", content)
        self.assertIn(self.patient_active.name, content)
        self.assertIn(self.patient_expired.name, content)
        self.assertIn(self.patient_none.name, content)
        self.assertIn("所属主任医生：", content)
        self.assertIn("所属工作室：", content)

        managed_patients = response.context["managed_patients"]
        unmanaged_patients = response.context["unmanaged_patients"]
        patient_by_id = {patient.id: patient for patient in managed_patients + unmanaged_patients}

        self.assertEqual(
            patient_by_id[self.patient_active.id].director_doctor_name,
            self.assignment_director.name,
        )
        self.assertEqual(
            patient_by_id[self.patient_active.id].affiliated_studio_name,
            self.assignment_studio.name,
        )
        self.assertEqual(
            patient_by_id[self.patient_expired.id].director_doctor_name,
            self.fallback_director.name,
        )
        self.assertEqual(
            patient_by_id[self.patient_expired.id].affiliated_studio_name,
            self.fallback_studio.name,
        )
        self.assertEqual(
            patient_by_id[self.patient_none.id].director_doctor_name,
            self.fallback_director.name,
        )
        self.assertEqual(
            patient_by_id[self.patient_none.id].affiliated_studio_name,
            self.fallback_studio.name,
        )
        self.assertIn(f"所属主任医生：{self.assignment_director.name}", content)
        self.assertIn(f"所属工作室：{self.assignment_studio.name}", content)
        self.assertIn(f"所属主任医生：{self.fallback_director.name}", content)
        self.assertIn(f"所属工作室：{self.fallback_studio.name}", content)

    @patch("web_doctor.views.workspace.TodoListService")
    @patch("web_doctor.views.workspace.ChatService")
    def test_mobile_patient_list_search_filters(self, MockChatService, MockTodoListService):
        mock_page = MagicMock()
        mock_page.paginator.count = 0
        MockTodoListService.get_todo_page.return_value = mock_page

        chat_service = MockChatService.return_value
        chat_service.get_or_create_patient_conversation.return_value = MagicMock()
        chat_service.get_unread_count.return_value = 0

        self.client.force_login(self.user)
        url = reverse("web_doctor:mobile_patient_list")
        response = self.client.get(url, {"q": "张三"})

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn(self.patient_active.name, content)
        self.assertNotIn(self.patient_expired.name, content)
        self.assertNotIn(self.patient_none.name, content)

    def test_mobile_home_has_patient_list_entry(self):
        self.client.force_login(self.user)
        url = reverse("web_doctor:mobile_home")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn(reverse("web_doctor:mobile_patient_list"), content)

