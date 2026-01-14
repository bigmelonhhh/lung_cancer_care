from django.test import TestCase, Client
from django.urls import reverse
from users.models import CustomUser, PatientProfile
from health_data.models import HealthMetric, MetricType
from django.utils import timezone
import datetime

class RecordViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        # 创建测试用户和患者
        self.user = CustomUser.objects.create_user(
            username='testpatient', 
            password='password',
            wx_openid='test_openid_record'
        )
        self.patient = PatientProfile.objects.create(user=self.user, name="Test Patient")
        self.client.force_login(self.user)

    def test_record_temperature_timezone_aware(self):
        """测试体温录入是否正确处理时区"""
        url = reverse('web_patient:record_temperature')
        # 模拟前端传入的 Beijing 时间字符串 (YYYY-MM-DD HH:MM)
        # 假设当前是北京时间 2026-01-11 19:46:00
        record_time_str = "2026-01-11 19:46"
        
        response = self.client.post(url, {
            'temperature': '36.5',
            'record_time': record_time_str,
            'patient_id': self.patient.id
        })
        
        # 1. 验证重定向
        # 期望重定向到 patient_home 且包含 temperature=true
        self.assertEqual(response.status_code, 302)
        target_url = response.url
        self.assertIn(reverse('web_patient:patient_home'), target_url)
        self.assertIn('temperature=true', target_url)

        # 2. 验证数据库存储的时间是否为 Aware
        metric = HealthMetric.objects.filter(
            patient=self.patient, 
            metric_type=MetricType.BODY_TEMPERATURE
        ).last()
        
        self.assertIsNotNone(metric)
        self.assertTrue(timezone.is_aware(metric.measured_at))
        
        # 验证转换后的 UTC 时间是否正确
        # 北京时间 19:46 -> UTC 11:46
        # 注意：Django 测试数据库默认可能使用 UTC，measured_at 取出来是 UTC 时间
        utc_expected = datetime.datetime(2026, 1, 11, 11, 46, tzinfo=datetime.timezone.utc)
        self.assertEqual(metric.measured_at, utc_expected)

    def test_record_bp_timezone_aware(self):
        """测试血压录入是否正确处理时区"""
        url = reverse('web_patient:record_bp')
        record_time_str = "2026-01-11 19:46"
        
        response = self.client.post(url, {
            'ssy': '120',
            'szy': '80',
            'heart': '75',
            'record_time': record_time_str,
            'patient_id': self.patient.id
        })
        
        self.assertEqual(response.status_code, 302)
        target_url = response.url
        self.assertIn('bp_hr=true', target_url)
        
        # 检查血压记录
        bp_metric = HealthMetric.objects.filter(
            patient=self.patient,
            metric_type=MetricType.BLOOD_PRESSURE
        ).last()
        self.assertTrue(timezone.is_aware(bp_metric.measured_at))
        
        # 检查心率记录
        hr_metric = HealthMetric.objects.filter(
            patient=self.patient,
            metric_type=MetricType.HEART_RATE
        ).last()
        self.assertTrue(timezone.is_aware(hr_metric.measured_at))

    def test_record_spo2_timezone_aware(self):
        """测试血氧录入是否正确处理时区"""
        url = reverse('web_patient:record_spo2')
        record_time_str = "2026-01-11 19:46"
        
        response = self.client.post(url, {
            'spo2': '98',
            'record_time': record_time_str,
            'patient_id': self.patient.id
        })
        
        self.assertEqual(response.status_code, 302)
        target_url = response.url
        self.assertIn('spo2=true', target_url)
        
        metric = HealthMetric.objects.filter(
            patient=self.patient,
            metric_type=MetricType.BLOOD_OXYGEN
        ).last()
        self.assertTrue(timezone.is_aware(metric.measured_at))
