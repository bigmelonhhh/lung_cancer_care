from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.models import TreatmentCycle
from core.models import choices as core_choices
from market.models import Order, Product
from users import choices as user_choices
from users.models import CustomUser, PatientProfile
from web_patient.services.home_plan_access import resolve_home_plan_access


class HomePlanAccessTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.user = CustomUser.objects.create_user(
            username="home_plan_access_user",
            password="password",
            user_type=user_choices.UserType.PATIENT,
            wx_openid="test_openid_home_plan_access",
        )
        self.patient = PatientProfile.objects.create(
            user=self.user,
            name="首页计划权限患者",
            phone="13800000010",
        )

    def _create_cycle(self, *, start_date=None, end_date=None, status=None):
        return TreatmentCycle.objects.create(
            patient=self.patient,
            name="体验疗程",
            start_date=start_date or self.today,
            end_date=end_date or self.today,
            cycle_days=1,
            status=status or core_choices.TreatmentCycleStatus.IN_PROGRESS,
        )

    def _create_paid_order(self, *, paid_at=None):
        product = Product.objects.create(
            name="首页权限 VIP",
            price=Decimal("199.00"),
            duration_days=30,
            is_active=True,
        )
        return Order.objects.create(
            patient=self.patient,
            product=product,
            amount=product.price,
            status=Order.Status.PAID,
            paid_at=paid_at or timezone.now(),
        )

    def test_member_has_full_plan_access_without_cycle(self):
        self._create_paid_order()

        access = resolve_home_plan_access(self.patient)

        self.assertEqual(access.mode, "member")
        self.assertTrue(access.can_view_daily_plan)
        self.assertTrue(access.can_view_steps)
        self.assertTrue(access.can_view_history)

    def test_non_member_with_current_cycle_has_trial_access(self):
        self._create_cycle()

        access = resolve_home_plan_access(self.patient)

        self.assertEqual(access.mode, "trial")
        self.assertTrue(access.can_view_daily_plan)
        self.assertFalse(access.can_view_steps)
        self.assertFalse(access.can_view_history)

    def test_non_member_with_open_ended_current_cycle_has_trial_access(self):
        TreatmentCycle.objects.create(
            patient=self.patient,
            name="开放式体验疗程",
            start_date=self.today,
            end_date=None,
            cycle_days=1,
            status=core_choices.TreatmentCycleStatus.IN_PROGRESS,
        )

        access = resolve_home_plan_access(self.patient)

        self.assertEqual(access.mode, "trial")
        self.assertTrue(access.can_view_daily_plan)

    def test_non_member_without_current_cycle_is_locked(self):
        scenarios = (
            {
                "start_date": self.today + timedelta(days=1),
                "end_date": self.today + timedelta(days=2),
            },
            {
                "start_date": self.today - timedelta(days=2),
                "end_date": self.today - timedelta(days=1),
            },
            {"status": core_choices.TreatmentCycleStatus.COMPLETED},
            {"status": core_choices.TreatmentCycleStatus.TERMINATED},
        )

        for index, cycle_kwargs in enumerate(scenarios):
            with self.subTest(cycle_kwargs=cycle_kwargs):
                TreatmentCycle.objects.all().delete()
                self._create_cycle(**cycle_kwargs)
                access = resolve_home_plan_access(self.patient)
                self.assertEqual(access.mode, "locked", index)
                self.assertFalse(access.can_view_daily_plan)

    def test_expired_member_with_current_cycle_uses_trial_access(self):
        self._create_paid_order(paid_at=timezone.now() - timedelta(days=60))
        self._create_cycle()

        access = resolve_home_plan_access(self.patient)

        self.assertEqual(access.mode, "trial")

    def test_plan_date_access_follows_member_trial_and_locked_capabilities(self):
        yesterday = self.today - timedelta(days=1)

        locked_access = resolve_home_plan_access(self.patient)
        self.assertFalse(
            locked_access.can_view_plan_date(self.today, as_of_date=self.today)
        )

        self._create_cycle()
        trial_access = resolve_home_plan_access(self.patient)
        self.assertTrue(
            trial_access.can_view_plan_date(self.today, as_of_date=self.today)
        )
        self.assertFalse(
            trial_access.can_view_plan_date(yesterday, as_of_date=self.today)
        )

        self._create_paid_order()
        member_patient = PatientProfile.objects.get(pk=self.patient.pk)
        member_access = resolve_home_plan_access(member_patient)
        self.assertTrue(
            member_access.can_view_plan_date(yesterday, as_of_date=self.today)
        )
