import json
import shutil
import tempfile
import logging
from datetime import date
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import DailyTask, CheckupLibrary
from core.models.choices import PlanItemCategory, TaskStatus, ReportType, CheckupCategory
from health_data.models.report_upload import ReportUpload, ReportImage
from users.models import CustomUser, PatientProfile


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class RecordCheckupTests(TestCase):
    def setUp(self):
        # 创建用户和患者
        self.user = CustomUser.objects.create_user(
            username="testuser", 
            password="password",
            wx_openid="test_openid_123"  # 添加 wx_openid
        )
        self.patient = PatientProfile.objects.create(user=self.user, name="Test Patient", phone="13800000001")
        
        # 登录
        self.client = Client()
        self.client.force_login(self.user)
        
        # 创建复查项目库
        self.checkup_lib = CheckupLibrary.objects.create(
            name="血常规",
            code="BLOOD_ROUTINE",
            category=CheckupCategory.BLOOD,
            related_report_type=ReportType.BLOOD_ROUTINE
        )
        
        # 创建今日复查任务
        self.today = timezone.now().date()
        self.task = DailyTask.objects.create(
            patient=self.patient,
            task_date=self.today,
            task_type=PlanItemCategory.CHECKUP,
            title="血常规",
            status=TaskStatus.PENDING,
            interaction_payload={"checkup_id": self.checkup_lib.id}
        )
        
        self.url = reverse('web_patient:record_checkup')

    def tearDown(self):
        # 清理临时文件
        shutil.rmtree(tempfile.gettempdir(), ignore_errors=True)

    def test_record_checkup_get(self):
        """测试 GET 请求获取复查任务页面"""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "web_patient/record_checkup.html")
        
        # 验证上下文数据
        self.assertEqual(response.context['checkup_date'], self.today.strftime("%Y-%m-%d"))
        self.assertEqual(len(response.context['checkup_items']), 1)
        self.assertEqual(response.context['checkup_items'][0]['name'], "血常规")
        self.assertEqual(response.context['checkup_items'][0]['id'], self.task.id)

    def test_record_checkup_post_success(self):
        """测试成功上传图片并完成任务"""
        # 模拟图片文件
        image = SimpleUploadedFile(
            "test_image.jpg",
            b"file_content",
            content_type="image/jpeg"
        )
        
        data = {
            f'images_{self.task.id}': [image]
        }
        
        # AJAX 请求
        response = self.client.post(
            self.url,
            data,
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        
        self.assertEqual(response.status_code, 200)
        json_response = response.json()
        self.assertEqual(json_response['status'], 'success')
        
        # 验证数据库变更
        # 1. 任务状态更新
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, TaskStatus.COMPLETED)
        
        # 2. ReportUpload 创建
        uploads = ReportUpload.objects.filter(related_task=self.task)
        self.assertEqual(uploads.count(), 1)
        
        # 3. ReportImage 创建
        images = ReportImage.objects.filter(upload=uploads.first())
        self.assertEqual(images.count(), 1)
        self.assertEqual(images.first().checkup_item, self.checkup_lib)

    def test_record_checkup_post_no_files(self):
        """测试未上传文件提交"""
        logging.disable(logging.CRITICAL)
        try:
            data = {} # 空数据
            
            response = self.client.post(
                self.url,
                data,
                HTTP_X_REQUESTED_WITH='XMLHttpRequest'
            )
            
            # 视图中如果没有任何任务上传了图片，返回 400
            self.assertEqual(response.status_code, 400)
            json_response = response.json()
            self.assertEqual(json_response['status'], 'error')
            
            # 验证任务状态未改变
            self.task.refresh_from_db()
            self.assertEqual(self.task.status, TaskStatus.PENDING)
        finally:
            logging.disable(logging.NOTSET)

    def test_record_checkup_post_invalid_file_type(self):
        """测试上传非法文件类型"""
        logging.disable(logging.CRITICAL)
        try:
            text_file = SimpleUploadedFile(
                "test.txt",
                b"text content",
                content_type="text/plain"
            )
            
            data = {
                f'images_{self.task.id}': [text_file]
            }
            
            response = self.client.post(
                self.url,
                data,
                HTTP_X_REQUESTED_WITH='XMLHttpRequest'
            )
            
            # 后端会忽略非法文件。如果所有文件都非法，则相当于没有上传文件，返回 400
            self.assertEqual(response.status_code, 400)
            
            # 验证没有创建图片记录
            self.assertEqual(ReportImage.objects.count(), 0)
        finally:
            logging.disable(logging.NOTSET)

    def test_record_checkup_multiple_tasks(self):
        """测试多个任务同时上传"""
        # 创建第二个任务对应的 CheckupLibrary
        checkup_lib2 = CheckupLibrary.objects.create(name="胸部CT", code="CT_CHEST", category=CheckupCategory.IMAGING)
        
        # 创建第二个任务
        task2 = DailyTask.objects.create(
            patient=self.patient,
            task_date=self.today,
            task_type=PlanItemCategory.CHECKUP,
            title="胸部CT",
            status=TaskStatus.PENDING
        )
        
        image1 = SimpleUploadedFile("img1.jpg", b"content", content_type="image/jpeg")
        image2 = SimpleUploadedFile("img2.png", b"content", content_type="image/png")
        
        data = {
            f'images_{self.task.id}': [image1],
            f'images_{task2.id}': [image2]
        }
        
        response = self.client.post(
            self.url,
            data,
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        
        self.assertEqual(response.status_code, 200)
        
        # 验证两个任务都已完成
        self.task.refresh_from_db()
        task2.refresh_from_db()
        self.assertEqual(self.task.status, TaskStatus.COMPLETED)
        self.assertEqual(task2.status, TaskStatus.COMPLETED)
        
        # 验证创建了两个 ReportUpload (因为是循环处理)
        self.assertEqual(ReportUpload.objects.count(), 2)

    def test_record_checkup_transaction_rollback(self):
        """测试异常时事务回滚"""
        import logging
        image = SimpleUploadedFile("test.jpg", b"content", content_type="image/jpeg")
        data = {f'images_{self.task.id}': [image]}
        
        # Suppress django.request logger to avoid "Internal Server Error" logs in console
        django_logger = logging.getLogger('django.request')
        previous_level = django_logger.getEffectiveLevel()
        django_logger.setLevel(logging.CRITICAL)
        
        try:
            # 模拟保存文件时抛出异常
            # 同时 patch logging.error 以抑制预期的错误日志输出
            with patch('health_data.models.report_upload.ReportUpload.objects.create') as mock_create, \
                 patch('logging.error'):
                mock_create.side_effect = Exception("Database error")
                
                response = self.client.post(
                    self.url,
                    data,
                    HTTP_X_REQUESTED_WITH='XMLHttpRequest'
                )
                
                self.assertEqual(response.status_code, 500)
                
                # 验证任务状态未改变（已回滚）
                self.task.refresh_from_db()
                self.assertEqual(self.task.status, TaskStatus.PENDING)
                
                # 验证没有残留数据
                self.assertEqual(ReportUpload.objects.count(), 0)
        finally:
            # Restore logger level
            django_logger.setLevel(previous_level)

    def test_delete_report_image(self):
        """测试删除已上传图片"""
        # 1. 准备数据：已上传的图片
        upload = ReportUpload.objects.create(
            patient=self.patient,
            upload_source=1,
            uploader_role=1,
            related_task=self.task
        )
        image = ReportImage.objects.create(
            upload=upload,
            image_url="/media/test.jpg",
            checkup_item=self.checkup_lib
        )
        
        delete_url = reverse('web_patient:delete_report_image', args=[image.id])
        
        # 2. 发起删除请求
        response = self.client.post(delete_url)
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'success')
        
        # 3. 验证数据库记录已删除
        self.assertFalse(ReportImage.objects.filter(id=image.id).exists())

    def test_delete_report_image_permission(self):
        """测试删除他人图片（权限控制）"""
        logging.disable(logging.CRITICAL)
        try:
            # 创建另一个用户的图片
            other_user = CustomUser.objects.create_user(username="other", password="password", wx_openid="other_openid")
            other_patient = PatientProfile.objects.create(user=other_user, name="Other", phone="13800000002")
            
            other_upload = ReportUpload.objects.create(
                patient=other_patient,
                upload_source=1,
                uploader_role=1
            )
            other_image = ReportImage.objects.create(
                upload=other_upload,
                image_url="/media/other.jpg"
            )
            
            delete_url = reverse('web_patient:delete_report_image', args=[other_image.id])
            
            # 当前用户尝试删除
            response = self.client.post(delete_url)
            
            # 预期：403 Forbidden
            self.assertEqual(response.status_code, 403)
            self.assertTrue(ReportImage.objects.filter(id=other_image.id).exists())
        finally:
            logging.disable(logging.NOTSET)
