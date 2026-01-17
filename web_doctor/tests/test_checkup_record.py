
import json
from datetime import date
from io import BytesIO

from django.test import TestCase, Client
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile

from users.models import DoctorProfile, PatientProfile, CustomUser
from health_data.models import ClinicalEvent, ReportImage
from core.models import CheckupLibrary, choices

class CheckupRecordTest(TestCase):
    def setUp(self):
        # 创建医生用户
        self.doctor_user = CustomUser.objects.create_user(
            username="doctor_test",
            password="password123",
            user_type=CustomUser.UserType.DOCTOR
        )
        self.doctor_profile = DoctorProfile.objects.create(
            user=self.doctor_user,
            name="Test Doctor",
            hospital="Test Hospital"
        )
        
        # 创建患者用户
        self.patient_user = CustomUser.objects.create_user(
            username="patient_test",
            password="password123",
            user_type=CustomUser.UserType.PATIENT
        )
        self.patient_profile = PatientProfile.objects.create(
            user=self.patient_user,
            name="Test Patient",
            phone="13800000000"
        )
        
        # 创建复查项目库
        self.checkup_item = CheckupLibrary.objects.create(
            name="血常规",
            code="BLOOD_ROUTINE",
            category=choices.CheckupCategory.LAB
        )
        self.checkup_item_other = CheckupLibrary.objects.create(
            name="其他",
            code="OTHER",
            category=choices.CheckupCategory.OTHER
        )
        
        self.client = Client()
        self.url = reverse("web_doctor:patient_checkup_create", args=[self.patient_profile.id])

    def test_create_checkup_record_success(self):
        """测试正常创建诊疗记录"""
        self.client.force_login(self.doctor_user)
        
        # 准备文件
        img1 = SimpleUploadedFile("test1.jpg", b"file_content", content_type="image/jpeg")
        img2 = SimpleUploadedFile("test2.jpg", b"file_content", content_type="image/jpeg")
        
        # 准备元数据
        metadata = [
            {"name": "test1.jpg", "category": "复查", "subcategory": "血常规"},
            {"name": "test2.jpg", "category": "门诊", "subcategory": ""}
        ]
        
        data = {
            "record_type": "复查",
            "report_date": "2023-10-01",
            "hospital": "协和医院",
            "remarks": "备注测试",
            "files[]": [img1, img2],
            "file_metadata": json.dumps(metadata)
        }
        
        response = self.client.post(self.url, data)
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "success")
        
        # 验证 ClinicalEvent
        event = ClinicalEvent.objects.first()
        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, 3) # 复查
        self.assertEqual(str(event.event_date), "2023-10-01")
        self.assertEqual(event.hospital_name, "协和医院")
        self.assertEqual(event.interpretation, "备注测试")
        self.assertEqual(event.created_by_doctor, self.doctor_profile)
        
        # 验证 ReportImage
        images = ReportImage.objects.filter(clinical_event=event)
        self.assertEqual(images.count(), 2)
        
        # 验证图片分类
        img1_obj = images.filter(checkup_item__name="血常规").first()
        self.assertIsNotNone(img1_obj)
        
        # 注意：对于非复查分类的图片（如门诊），代码逻辑会将其归为"其他"
        img2_obj = images.filter(checkup_item__name="其他").first()
        self.assertIsNotNone(img2_obj)

    def test_create_checkup_record_missing_params(self):
        """测试缺少必填参数"""
        self.client.force_login(self.doctor_user)
        
        data = {
            "hospital": "Test",
        }
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 400)
        self.assertIn("缺少必填参数", response.json()["message"])

    def test_create_checkup_record_no_files(self):
        """测试未上传文件"""
        self.client.force_login(self.doctor_user)
        
        data = {
            "record_type": "复查",
            "report_date": "2023-10-01",
            "file_metadata": "[]"
        }
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 400)
        self.assertIn("请上传至少一张图片", response.json()["message"])

    def test_create_checkup_record_invalid_json(self):
        """测试元数据 JSON 格式错误"""
        self.client.force_login(self.doctor_user)
        
        data = {
            "record_type": "复查",
            "report_date": "2023-10-01",
            "file_metadata": "invalid json"
        }
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 400)
        self.assertIn("元数据格式错误", response.json()["message"])

    def test_permission_denied(self):
        """测试权限控制"""
        # 未登录
        response = self.client.post(self.url, {})
        self.assertEqual(response.status_code, 302) # 重定向到登录
        
        # 非医生/助理用户
        self.client.force_login(self.patient_user)
        response = self.client.post(self.url, {})
        # check_doctor_or_assistant 装饰器通常会抛出 403 或重定向
        # 假设装饰器实现是返回 403 或其他错误响应，具体取决于实现
        # 如果装饰器只是重定向到 login，则是 302。
        # 这里我们检查是否禁止访问
        self.assertNotEqual(response.status_code, 200)
