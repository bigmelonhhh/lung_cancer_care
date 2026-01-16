from unittest.mock import patch
from django.test import TestCase
from django.utils import timezone
from datetime import timedelta, date
from django.contrib.auth import get_user_model
from users.models import PatientProfile
from core.models import TreatmentCycle
from web_doctor.views.indicators import build_indicators_context

User = get_user_model()

class IndicatorsHemoptysisTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testpatient_hemo', password='password', wx_openid='test_openid_hemo')
        self.patient = PatientProfile.objects.create(user=self.user, name="Test Patient Hemo")
        self.today = timezone.localdate()
        
        # 创建一个疗程以方便确定日期范围
        self.start_date = self.today - timedelta(days=5)
        self.end_date = self.today
        self.cycle = TreatmentCycle.objects.create(
            patient=self.patient, 
            name="Cycle Hemo", 
            start_date=self.start_date, 
            end_date=self.end_date
        )

    @patch('web_doctor.views.indicators.QuestionnaireSubmissionService.list_daily_cough_hemoptysis_flags')
    def test_hemoptysis_data_integration(self, mock_list_flags):
        """测试咯血数据集成：正常数据转换"""
        # Mock 返回数据
        # 假设日期范围是 [today-5, today]，共6天
        # 模拟：第一天True，第二天False，其他无数据
        
        mock_data = [
            {"date": self.start_date, "has_hemoptysis": True},
            {"date": self.start_date + timedelta(days=1), "has_hemoptysis": False},
        ]
        mock_list_flags.return_value = mock_data
        
        context = build_indicators_context(
            self.patient, 
            cycle_id=str(self.cycle.id),
            filter_type='cycle'
        )
        
        # 验证调用参数
        mock_list_flags.assert_called_once()
        call_kwargs = mock_list_flags.call_args[1]
        self.assertEqual(call_kwargs['patient'], self.patient)
        self.assertEqual(call_kwargs['start_date'], self.start_date)
        # end_date 在 build_indicators_context 中逻辑可能有点复杂，如果是 cycle，end_date 就是 cycle.end_date
        self.assertEqual(call_kwargs['end_date'], self.end_date)
        
        # 验证结果
        cough_table = context['cough_table']
        self.assertIn('rows', cough_table)
        self.assertEqual(len(cough_table['rows']), 1)
        row = cough_table['rows'][0]
        self.assertEqual(row['label'], "咯血")
        
        values = row['values']
        # values 长度应该等于日期天数 (6天)
        self.assertEqual(len(values), 6)
        
        # 第一天 (start_date) -> True -> "有"
        self.assertEqual(values[0], "有")
        # 第二天 (start_date + 1) -> False -> "无"
        self.assertEqual(values[1], "无")
        # 第三天 (start_date + 2) -> 无数据 -> "-"
        self.assertEqual(values[2], "-")

    @patch('web_doctor.views.indicators.QuestionnaireSubmissionService.list_daily_cough_hemoptysis_flags')
    def test_hemoptysis_no_data(self, mock_list_flags):
        """测试咯血数据集成：无数据"""
        mock_list_flags.return_value = []
        
        context = build_indicators_context(
            self.patient, 
            cycle_id=str(self.cycle.id),
            filter_type='cycle'
        )
        
        values = context['cough_table']['rows'][0]['values']
        # 所有都是 "-"
        for val in values:
            self.assertEqual(val, "-")

    @patch('web_doctor.views.indicators.QuestionnaireSubmissionService.list_daily_cough_hemoptysis_flags')
    @patch('web_doctor.views.indicators.logger.error')
    def test_hemoptysis_error_handling(self, mock_logger, mock_list_flags):
        """测试咯血数据集成：异常处理"""
        mock_list_flags.side_effect = Exception("Service error")
        
        context = build_indicators_context(
            self.patient, 
            cycle_id=str(self.cycle.id),
            filter_type='cycle'
        )
        
        values = context['cough_table']['rows'][0]['values']
        # 异常时应该兜底显示 "-"
        for val in values:
            self.assertEqual(val, "-")
