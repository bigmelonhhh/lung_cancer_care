from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from market.models import Order, Product
from users.models import PatientProfile


class PatientProfileMembershipStatusTests(TestCase):
    def _create_patient(self, phone_suffix: int) -> PatientProfile:
        return PatientProfile.objects.create(
            phone=f"1380000{phone_suffix:04d}",
            name="测试患者",
        )

    def _create_paid_order(
        self,
        *,
        patient: PatientProfile,
        paid_at_delta_days: int,
        duration_days: int,
    ) -> Order:
        product = Product.objects.create(
            name=f"服务包-{duration_days}天",
            price="100.00",
            duration_days=duration_days,
            is_active=True,
        )
        paid_at = timezone.now() + timedelta(days=paid_at_delta_days)
        return Order.objects.create(
            patient=patient,
            product=product,
            amount=product.price,
            status=Order.Status.PAID,
            paid_at=paid_at,
        )

    def test_service_status_none(self):
        patient = self._create_patient(1)
        self.assertEqual(patient.service_status, "none")

    def test_service_status_expired(self):
        patient = self._create_patient(2)
        self._create_paid_order(patient=patient, paid_at_delta_days=-10, duration_days=3)
        self.assertEqual(patient.service_status, "expired")

    def test_service_status_active(self):
        patient = self._create_patient(3)
        self._create_paid_order(patient=patient, paid_at_delta_days=-1, duration_days=5)
        self.assertEqual(patient.service_status, "active")
