from datetime import timedelta, datetime
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model
from users.models import PatientProfile
from core.models import TreatmentCycle, choices
from health_data.models import HealthMetric, MetricType
from web_doctor.views.indicators import build_indicators_context

User = get_user_model()

class IndicatorsLogicTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testpatient', password='password', wx_openid='test_openid_123')
        self.patient = PatientProfile.objects.create(user=self.user, name="Test Patient")
        self.today = timezone.localdate()

    def test_default_view_active_cycle(self):
        """测试默认视图是否选中当前进行中的疗程"""
        # Create past cycle
        past_start = self.today - timedelta(days=60)
        past_end = self.today - timedelta(days=31)
        c1 = TreatmentCycle.objects.create(
            patient=self.patient, 
            name="Cycle 1", 
            start_date=past_start, 
            end_date=past_end,
            status=choices.TreatmentCycleStatus.COMPLETED
        )
        
        # Create active cycle
        active_start = self.today - timedelta(days=10)
        active_end = self.today + timedelta(days=20)
        c2 = TreatmentCycle.objects.create(
            patient=self.patient, 
            name="Cycle 2", 
            start_date=active_start, 
            end_date=active_end,
            status=choices.TreatmentCycleStatus.IN_PROGRESS
        )
        
        context = build_indicators_context(self.patient)
        
        self.assertEqual(context['current_cycle_id'], c2.id)
        # current_start_date is empty in default view to keep inputs clear
        self.assertEqual(context['current_start_date'], "")
        # Verify the actual query range via 'dates'
        # Since start and end are in the same year (2026), format is m-d
        self.assertEqual(context['dates'][0], active_start.strftime("%m-%d"))
        self.assertTrue(context['is_default_view'])
        self.assertEqual(context['current_filter_type'], 'cycle')

    def test_status_priority(self):
        """测试状态优先级：即使日期吻合，也优先选中状态为 IN_PROGRESS 的疗程"""
        # Case: Two cycles, one completed (but date matches today?), one in progress.
        # Actually, "completed" usually implies end_date < today, but let's simulate a case
        # where a cycle was manually terminated early but dates might still overlap or be irrelevant if we trust status.
        
        # Cycle 1: Completed, but date range covers today (e.g. terminated early)
        start1 = self.today - timedelta(days=5)
        end1 = self.today + timedelta(days=5)
        c1 = TreatmentCycle.objects.create(
            patient=self.patient,
            name="Terminated Cycle",
            start_date=start1,
            end_date=end1,
            status=choices.TreatmentCycleStatus.COMPLETED
        )

        # Cycle 2: In Progress
        start2 = self.today - timedelta(days=2)
        end2 = self.today + timedelta(days=10)
        c2 = TreatmentCycle.objects.create(
            patient=self.patient,
            name="Active Cycle",
            start_date=start2,
            end_date=end2,
            status=choices.TreatmentCycleStatus.IN_PROGRESS
        )

        context = build_indicators_context(self.patient)
        
        # Should select c2 because it is IN_PROGRESS
        self.assertEqual(context['current_cycle_id'], c2.id)

    def test_default_view_fallback_latest_cycle(self):
        """测试无进行中疗程时，兜底显示最近一个疗程"""
        # Create past cycle only
        past_start = self.today - timedelta(days=60)
        past_end = self.today - timedelta(days=31)
        c1 = TreatmentCycle.objects.create(
            patient=self.patient, 
            name="Cycle 1", 
            start_date=past_start, 
            end_date=past_end,
            status=choices.TreatmentCycleStatus.COMPLETED
        )
        
        context = build_indicators_context(self.patient)
        
        self.assertEqual(context['current_cycle_id'], c1.id)
        self.assertEqual(context['current_start_date'], "")
        self.assertEqual(context['dates'][0], past_start.strftime("%m-%d"))

    def test_medication_data_future_logic(self):
        """测试服药记录数据结构及未来日期逻辑"""
        # Set range covering yesterday, today, tomorrow
        start_date = self.today - timedelta(days=1)
        end_date = self.today + timedelta(days=1)
        
        # Create record for yesterday
        # Note: HealthMetric uses DateTimeField, so we need make_aware
        measured_at = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))
        HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.USE_MEDICATED,
            measured_at=measured_at,
            value_main=1
        )
        
        context = build_indicators_context(
            self.patient, 
            start_date_str=start_date.isoformat(), 
            end_date_str=end_date.isoformat(),
            filter_type='date'
        )
        
        med_data = context['medication_data']
        # Expect 3 days: Yesterday, Today, Tomorrow
        self.assertEqual(len(med_data), 3)
        
        # Verify structure and dates
        yesterday_rec = med_data[0]
        today_rec = med_data[1]
        tomorrow_rec = med_data[2]
        
        self.assertEqual(yesterday_rec['date'], start_date)
        self.assertTrue(yesterday_rec['taken'])
        
        self.assertEqual(today_rec['date'], self.today)
        self.assertFalse(today_rec['taken'])
        
        self.assertEqual(tomorrow_rec['date'], end_date)
        self.assertFalse(tomorrow_rec['taken'])
        
        # Verify comparison logic logic works (conceptually)
        # In template: if record.date > current_date
        current_date = context['current_date']
        self.assertEqual(current_date, self.today)
        
        self.assertFalse(yesterday_rec['date'] > current_date)
        self.assertFalse(today_rec['date'] > current_date)
        self.assertTrue(tomorrow_rec['date'] > current_date)

    @patch("web_doctor.views.indicators.HealthMetricService.query_metrics_by_type")
    def test_indicators_query_end_date_inclusive(self, mock_query):
        start_date = self.today - timedelta(days=1)
        end_date = self.today
        mock_query.return_value = SimpleNamespace(object_list=[])

        build_indicators_context(
            self.patient,
            start_date_str=start_date.isoformat(),
            end_date_str=end_date.isoformat(),
            filter_type="date",
        )

        _, kwargs = mock_query.call_args
        self.assertEqual(kwargs["end_date"].date(), end_date + timedelta(days=1))
        self.assertEqual(kwargs["end_date"].time(), datetime.min.time())
