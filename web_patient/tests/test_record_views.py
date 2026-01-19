import datetime
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from health_data.models import HealthMetric, MetricType
from users.models import CustomUser, PatientProfile

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
        # 期望重定向回当前页面 (刷新)
        self.assertEqual(response.status_code, 302)
        target_url = response.url
        self.assertEqual(target_url, url)
        
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
        self.assertEqual(target_url, url)
        
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
        self.assertEqual(target_url, url)
        
        metric = HealthMetric.objects.filter(
            patient=self.patient,
            metric_type=MetricType.BLOOD_OXYGEN
        ).last()
        self.assertTrue(timezone.is_aware(metric.measured_at))

    def test_health_record_detail_end_date_inclusive(self):
        tz = timezone.get_current_timezone()
        month = "2025-01"
        month_end = timezone.make_aware(
            datetime.datetime(2025, 1, 31, 23, 59, 59), tz
        )
        boundary_next_month = timezone.make_aware(
            datetime.datetime(2025, 2, 1, 0, 0), tz
        )

        HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BODY_TEMPERATURE,
            measured_at=month_end,
            value_main=Decimal("36.5"),
        )
        HealthMetric.objects.create(
            patient=self.patient,
            metric_type=MetricType.BODY_TEMPERATURE,
            measured_at=boundary_next_month,
            value_main=Decimal("36.9"),
        )

        response = self.client.get(
            reverse("web_patient:health_record_detail"),
            {"type": "temperature", "title": "体温", "month": month},
        )

        self.assertEqual(response.status_code, 200)
        records = response.context["records"]
        dates = sorted(item["date"] for item in records)
        self.assertEqual(dates, ["2025-01-31", "2025-02-01"])
