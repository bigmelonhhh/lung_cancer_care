from django.test import TestCase, RequestFactory
from django.contrib.auth.models import AnonymousUser
from users.models import CustomUser, PatientProfile
from users.choices import UserType
from patient_alerts.models import PatientAlert, AlertEventType, AlertLevel
from health_data.models import MetricType
from core.models import QuestionnaireCode
from django.utils import timezone
from datetime import timedelta
from web_patient.views.record import health_records
from market.models import Product, Order
from decimal import Decimal

class HealthRecordsAbnormalCountTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        
        # 创建用户和患者
        self.user = CustomUser.objects.create_user(
            username='testpatient',
            password='password123',
            user_type=UserType.PATIENT,
            wx_openid="test_openid_12345"
        )
        self.patient = PatientProfile.objects.create(
            user=self.user,
            name="Test Patient",
            phone="13800138000"
        )
        product = Product.objects.create(
            name="VIP 服务包",
            price=Decimal("199.00"),
            duration_days=1,
            is_active=True,
        )
        Order.objects.create(
            patient=self.patient,
            product=product,
            amount=Decimal("199.00"),
            status=Order.Status.PAID,
            paid_at=timezone.now(),
        )
        
        # 模拟登录
        self.client.force_login(self.user)

    def test_abnormal_count_normal(self):
        """测试正常情况下的异常统计"""
        # 创建一个体温异常报警 (MetricType.BODY_TEMPERATURE)
        PatientAlert.objects.create(
            patient=self.patient,
            event_type=AlertEventType.DATA,
            event_level=AlertLevel.MILD,
            is_active=True,
            event_time=timezone.now(),
            source_type="metric",
            source_payload={
                "metric_type": MetricType.BODY_TEMPERATURE,
                "value": 39.0
            }
        )
        
        # 创建一个咳嗽问卷异常报警 (QuestionnaireCode.Q_COUGH)
        PatientAlert.objects.create(
            patient=self.patient,
            event_type=AlertEventType.QUESTIONNAIRE,
            event_level=AlertLevel.MODERATE,
            is_active=True,
            event_time=timezone.now(),
            source_type="questionnaire",
            source_payload={
                "questionnaire_code": QuestionnaireCode.Q_COUGH,
                "score": 5
            }
        )

        request = self.factory.get('/p/health/records/')
        request.user = self.user
        request.patient = self.patient
        
        # 改用 client 请求
        response = self.client.get('/p/health/records/')
        
        self.assertEqual(response.status_code, 200)
        context = response.context
        
        # 检查体温异常数
        temp_stat = next(item for item in context['health_stats'] if item['type'] == 'temperature')
        self.assertEqual(temp_stat['abnormal'], 1)
        
        # 检查其他指标异常数应为 0
        bp_stat = next(item for item in context['health_stats'] if item['type'] == 'bp')
        self.assertEqual(bp_stat['abnormal'], 0)
        
        # 检查咳嗽问卷异常数
        cough_stat = next(item for item in context['health_survey_stats'] if item['type'] == 'cough')
        self.assertEqual(cough_stat['abnormal'], 1)

    def test_abnormal_count_inactive(self):
        """测试已处理（非激活）的报警不计入统计"""
        PatientAlert.objects.create(
            patient=self.patient,
            event_type=AlertEventType.DATA,
            event_level=AlertLevel.MILD,
            is_active=False,  # 已处理
            event_time=timezone.now(),
            source_type="metric",
            source_payload={
                "metric_type": MetricType.BODY_TEMPERATURE,
                "value": 38.5
            }
        )
        
        response = self.client.get('/p/health/records/')
        context = response.context
        
        temp_stat = next(item for item in context['health_stats'] if item['type'] == 'temperature')
        self.assertEqual(temp_stat['abnormal'], 0)

    def test_abnormal_count_date_range(self):
        """测试日期范围过滤（未来日期的报警不应计入，如果 end_date 是今天）"""
        # 创建一个明天的报警
        future_time = timezone.now() + timedelta(days=1)
        PatientAlert.objects.create(
            patient=self.patient,
            event_type=AlertEventType.DATA,
            event_level=AlertLevel.MILD,
            is_active=True,
            event_time=future_time,
            source_type="metric",
            source_payload={
                "metric_type": MetricType.BODY_TEMPERATURE,
                "value": 39.5
            }
        )
        
        response = self.client.get('/p/health/records/')
        context = response.context
        
        temp_stat = next(item for item in context['health_stats'] if item['type'] == 'temperature')
        # 视图中 end_date = timezone.now().date()
        # 如果 future_time.date() > now.date()，则不应计入
        self.assertEqual(temp_stat['abnormal'], 0)

    def test_abnormal_count_no_data(self):
        """测试无数据情况"""
        response = self.client.get('/p/health/records/')
        context = response.context
        
        for item in context['health_stats']:
            self.assertEqual(item['abnormal'], 0)
            
        for item in context['health_survey_stats']:
            self.assertEqual(item['abnormal'], 0)
