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


class PatientListServiceStatusGroupsTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="doc_status",
            password="password",
            user_type=2,
            phone="13900139001",
        )
        self.doctor_profile = DoctorProfile.objects.create(user=self.user, name="Dr. Status")
        self.user.doctor_profile = self.doctor_profile
        self.user.save()

        self.fallback_director_user = User.objects.create_user(
            username="doc_status_fallback_director",
            password="password",
            user_type=2,
            phone="13900139011",
        )
        self.fallback_director = DoctorProfile.objects.create(
            user=self.fallback_director_user,
            name="Dr. Fallback Director",
        )
        self.fallback_director_user.doctor_profile = self.fallback_director
        self.fallback_director_user.save()

        self.assignment_director_user = User.objects.create_user(
            username="doc_status_assignment_director",
            password="password",
            user_type=2,
            phone="13900139012",
        )
        self.assignment_director = DoctorProfile.objects.create(
            user=self.assignment_director_user,
            name="Dr. Assignment Director",
        )
        self.assignment_director_user.doctor_profile = self.assignment_director
        self.assignment_director_user.save()

        self.fallback_studio = DoctorStudio.objects.create(
            name="兜底工作室",
            code="STATUS_FALLBACK_001",
            owner_doctor=self.fallback_director,
        )
        self.assignment_studio = DoctorStudio.objects.create(
            name="归属工作室",
            code="STATUS_ASSIGN_001",
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
            phone="13800138001",
            doctor=self.doctor_profile,
        )
        self.patient_expired = PatientProfile.objects.create(
            name="李四",
            phone="13800138002",
            doctor=self.doctor_profile,
        )
        self.patient_none = PatientProfile.objects.create(
            name="赵六",
            phone="13800138003",
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
    def test_patient_list_grouped_by_service_status(self, MockChatService, MockTodoListService):
        mock_page = MagicMock()
        mock_page.paginator.count = 0
        MockTodoListService.get_todo_page.return_value = mock_page

        chat_service = MockChatService.return_value
        chat_service.get_or_create_patient_conversation.return_value = MagicMock()
        chat_service.get_unread_count.return_value = 0

        self.client.force_login(self.user)
        url = reverse("web_doctor:doctor_workspace_patient_list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

        managed_ids = {p.id for p in response.context["managed_patients"]}
        stopped_ids = {p.id for p in response.context["stopped_patients"]}
        unpaid_ids = {p.id for p in response.context["unpaid_patients"]}

        self.assertSetEqual(managed_ids, {self.patient_active.id})
        self.assertSetEqual(stopped_ids, {self.patient_expired.id})
        self.assertSetEqual(unpaid_ids, {self.patient_none.id})

        managed_patient = response.context["managed_patients"][0]
        stopped_patient = response.context["stopped_patients"][0]
        unpaid_patient = response.context["unpaid_patients"][0]

        self.assertEqual(managed_patient.director_doctor_name, self.assignment_director.name)
        self.assertEqual(managed_patient.affiliated_studio_name, self.assignment_studio.name)
        self.assertEqual(stopped_patient.director_doctor_name, self.fallback_director.name)
        self.assertEqual(stopped_patient.affiliated_studio_name, self.fallback_studio.name)
        self.assertEqual(unpaid_patient.director_doctor_name, self.fallback_director.name)
        self.assertEqual(unpaid_patient.affiliated_studio_name, self.fallback_studio.name)

        content = response.content.decode("utf-8")
        self.assertIn(f"主任：{self.assignment_director.name}", content)
        self.assertIn(f"主任：{self.fallback_director.name}", content)

