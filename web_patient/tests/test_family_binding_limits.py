from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from market.models import Order, Product
from users import choices
from users.models import CustomUser, PatientProfile, PatientRelation
from users.services.patient import PatientService


class FamilyBindingLimitTests(TestCase):
    def setUp(self):
        self.service = PatientService()
        self.patient_user = CustomUser.objects.create_user(
            username="family_limit_patient",
            password="password",
            user_type=choices.UserType.PATIENT,
            wx_openid="family_limit_patient_openid",
        )
        self.patient = PatientProfile.objects.create(
            user=self.patient_user,
            name="亲情额度测试患者",
            phone="13800001000",
        )

    def _create_family_user(self, index: int) -> CustomUser:
        return CustomUser.objects.create_user(
            username=f"family_limit_user_{index}",
            password="password",
            user_type=choices.UserType.PATIENT,
            wx_openid=f"family_limit_openid_{index}",
        )

    def _activate_membership(self) -> None:
        product = Product.objects.create(
            name="VIP 服务包",
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

    def _bind_family(self, index: int) -> CustomUser:
        family_user = self._create_family_user(index)
        self.service.process_binding(
            family_user,
            self.patient.id,
            choices.RelationType.CHILD,
            relation_name=f"家属{index}",
        )
        return family_user

    def test_free_patient_cannot_bind_second_active_family(self):
        self._bind_family(1)
        second_family = self._create_family_user(2)

        with self.assertRaisesMessage(
            ValidationError,
            "免费用户最多可绑定 1 个亲情账号。",
        ):
            self.service.process_binding(
                second_family,
                self.patient.id,
                choices.RelationType.CHILD,
            )

        self.assertEqual(
            PatientRelation.objects.filter(patient=self.patient, is_active=True).count(),
            1,
        )

    def test_anonymous_free_binding_landing_uses_free_limit_message(self):
        self._bind_family(1)

        response = self.client.get(
            reverse("web_patient:bind_landing", args=[self.patient.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "免费用户最多可绑定 1 个亲情账号。")
        self.assertNotContains(
            response,
            "一个患者最多可绑定 5 个亲情账号",
        )

    def test_paid_patient_can_bind_five_but_not_six(self):
        self._activate_membership()
        for index in range(1, 6):
            self._bind_family(index)
        sixth_family = self._create_family_user(6)

        with self.assertRaisesMessage(
            ValidationError,
            "最多可绑定 5 个亲情账号。",
        ):
            self.service.process_binding(
                sixth_family,
                self.patient.id,
                choices.RelationType.CHILD,
            )

        self.assertEqual(
            PatientRelation.objects.filter(patient=self.patient, is_active=True).count(),
            5,
        )

    def test_existing_active_relation_remains_idempotent_at_limit(self):
        family_user = self._bind_family(1)

        self.service.process_binding(
            family_user,
            self.patient.id,
            choices.RelationType.PARENT,
            relation_name="父亲",
        )

        relation = PatientRelation.objects.get(
            patient=self.patient,
            user=family_user,
        )
        self.assertTrue(relation.is_active)
        self.assertEqual(relation.relation_type, choices.RelationType.PARENT)
        self.assertEqual(relation.relation_name, "父亲")

    def test_free_patient_cannot_bypass_limit_through_bind_submit(self):
        self._bind_family(1)
        second_family = self._create_family_user(2)
        self.client.force_login(second_family)

        response = self.client.post(
            reverse("web_patient:bind_submit", args=[self.patient.id]),
            {
                "relation_type": choices.RelationType.CHILD,
                "relation_name": "第二位家属",
            },
        )

        self.assertRedirects(
            response,
            reverse("web_patient:bind_landing", args=[self.patient.id]),
        )
        messages = [str(message) for message in response.wsgi_request._messages]
        self.assertIn("免费用户最多可绑定 1 个亲情账号。", messages)
        self.assertFalse(
            PatientRelation.objects.filter(
                patient=self.patient,
                user=second_family,
                is_active=True,
            ).exists()
        )

    @patch(
        "web_patient.views.family.patient_service.generate_bind_qrcode",
        return_value="https://example.com/family-qrcode",
    )
    def test_free_patient_can_unbind_family(self, _generate_qrcode):
        family_user = self._bind_family(1)
        relation = PatientRelation.objects.get(
            patient=self.patient,
            user=family_user,
        )
        self.client.force_login(self.patient_user)

        response = self.client.post(
            reverse("web_patient:unbind_family"),
            {"relation_id": relation.id},
        )

        self.assertEqual(response.status_code, 302)
        relation.refresh_from_db()
        self.assertFalse(relation.is_active)

    def test_expired_patient_keeps_existing_relations_but_cannot_add(self):
        first_family = self._bind_family(1)
        second_family = self._create_family_user(2)
        PatientRelation.objects.create(
            patient=self.patient,
            user=second_family,
            relation_type=choices.RelationType.CHILD,
            is_active=True,
        )
        third_family = self._create_family_user(3)

        with self.assertRaisesMessage(
            ValidationError,
            "免费用户最多可绑定 1 个亲情账号。",
        ):
            self.service.process_binding(
                third_family,
                self.patient.id,
                choices.RelationType.CHILD,
            )

        self.assertEqual(
            PatientRelation.objects.filter(patient=self.patient, is_active=True).count(),
            2,
        )
        self.assertTrue(
            PatientRelation.objects.filter(
                patient=self.patient,
                user=first_family,
                is_active=True,
            ).exists()
        )
