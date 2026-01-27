from datetime import date, timedelta

from django.test import TestCase

from core.models import TreatmentCycle, choices
from users.models import PatientProfile


class TreatmentCycleStatusDisplayTests(TestCase):
    def setUp(self):
        self.patient = PatientProfile.objects.create(phone="13900009990", name="状态显示患者")

    def test_future_cycle_shows_not_started(self):
        today = date.today()
        cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="未来疗程",
            start_date=today + timedelta(days=3),
            end_date=today + timedelta(days=10),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        self.assertEqual(cycle.get_status_display(), "未开始")

    def test_in_range_cycle_shows_in_progress(self):
        today = date.today()
        cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="进行中疗程",
            start_date=today - timedelta(days=2),
            end_date=today + timedelta(days=2),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        self.assertEqual(cycle.get_status_display(), "进行中")

    def test_past_cycle_shows_completed_even_if_status_in_progress(self):
        today = date.today()
        cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="已结束疗程",
            start_date=today - timedelta(days=10),
            end_date=today - timedelta(days=1),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.IN_PROGRESS,
        )
        self.assertEqual(cycle.get_status_display(), "已结束")

    def test_terminated_cycle_shows_terminated(self):
        today = date.today()
        cycle = TreatmentCycle.objects.create(
            patient=self.patient,
            name="已终止疗程",
            start_date=today - timedelta(days=2),
            end_date=today + timedelta(days=10),
            cycle_days=21,
            status=choices.TreatmentCycleStatus.TERMINATED,
        )
        self.assertEqual(cycle.get_status_display(), "已终止")
