from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import date
from web_doctor.views.reports_history_data import handle_reports_history_section, patient_report_update, create_consultation_record
from health_data.models import ClinicalEvent, ReportImage, ReportUpload, UploadSource
from core.models import CheckupLibrary
from users.models import DoctorProfile, PatientProfile
from users import choices
import json

User = get_user_model()

class ConsultationRecordsTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        
        # Doctor
        self.doctor_user = User.objects.create_user(
            username='doctor', 
            password='password',
            user_type=choices.UserType.DOCTOR,
            phone="13800000000"
        )
        self.doctor = DoctorProfile.objects.create(user=self.doctor_user, name='Test Doctor')
        
        # Patient
        self.patient_user = User.objects.create_user(
            username='patient', 
            user_type=choices.UserType.PATIENT,
            wx_openid="test_openid"
        )
        self.patient = PatientProfile.objects.create(user=self.patient_user, name='Test Patient')
        
        # Checkup Library
        self.checkup_item = CheckupLibrary.objects.create(name="血常规")
        
        # Create Clinical Event (Normal)
        self.event1 = ClinicalEvent.objects.create(
            patient=self.patient,
            event_type=1, # 门诊
            event_date=date(2025, 1, 1),
            created_by_doctor=self.doctor,
            interpretation="Test Interpretation"
        )
        
        # Images for event1
        self.upload1 = ReportUpload.objects.create(patient=self.patient, upload_source=UploadSource.DOCTOR_BACKEND)
        self.image1 = ReportImage.objects.create(
            upload=self.upload1,
            image_url="http://test.com/1.jpg",
            record_type=1,
            clinical_event=self.event1,
            report_date=date(2025, 1, 1)
        )
        
        # Create Clinical Event (Missing Fields)
        self.event2 = ClinicalEvent.objects.create(
            patient=self.patient,
            event_type=3, # 复查
            event_date=date(2025, 1, 2),
            # created_by_doctor is None
            interpretation="" # Empty
        )
        
        # Images for event2
        self.image2 = ReportImage.objects.create(
            upload=self.upload1,
            image_url="http://test.com/2.jpg",
            record_type=3,
            checkup_item=self.checkup_item,
            clinical_event=self.event2,
            report_date=date(2025, 1, 2)
        )

    def test_normal_data_mapping(self):
        """测试正常数据返回场景"""
        request = self.factory.get('/doctor/workspace/reports?tab=records')
        request.user = self.doctor_user
        
        context = {"patient": self.patient}
        handle_reports_history_section(request, context)
        
        reports_page = context.get("reports_page")
        reports = reports_page.object_list
        
        # Should have 2 reports
        self.assertEqual(len(reports), 2)
        
        # Check event1 (Normal)
        # Sort order is usually -event_date, so event2 (Jan 2) should be first, event1 (Jan 1) second.
        # Check ID
        report1 = next(r for r in reports if r["id"] == self.event1.id)
        self.assertEqual(report1["date"], date(2025, 1, 1))
        self.assertEqual(report1["record_type"], "门诊")
        self.assertEqual(report1["archiver"], "Test Doctor")
        self.assertEqual(report1["interpretation"], "Test Interpretation")
        self.assertEqual(report1["image_count"], 1)
        self.assertEqual(report1["images"][0]["url"], "http://test.com/1.jpg")
        self.assertEqual(report1["images"][0]["category"], "门诊")

    def test_missing_fields_mapping(self):
        """测试接口返回字段不全场景"""
        request = self.factory.get('/doctor/workspace/reports?tab=records')
        request.user = self.doctor_user
        
        context = {"patient": self.patient}
        handle_reports_history_section(request, context)
        
        reports = context.get("reports_page").object_list
        report2 = next(r for r in reports if r["id"] == self.event2.id)
        
        # Check defaults
        self.assertEqual(report2["archiver"], "-后台接口未定义")
        self.assertEqual(report2["interpretation"], "") 
        self.assertEqual(report2["record_type"], "复查")
        self.assertEqual(report2["sub_category"], "血常规")
        self.assertEqual(report2["images"][0]["category"], "复查-血常规")

    def test_exception_data_handling(self):
        """测试异常数据处理场景 (e.g. invalid date params)"""
        # Test invalid date param - should be ignored and return all
        request = self.factory.get('/doctor/workspace/reports?tab=records&startDate=invalid-date')
        request.user = self.doctor_user
        
        context = {"patient": self.patient}
        handle_reports_history_section(request, context)
        
        reports = context.get("reports_page").object_list
        self.assertEqual(len(reports), 2)

    def test_update_record(self):
        """测试更新记录"""
        # Update event1 to Checkup
        payload = {
            "record_type": "复查",
            "interpretation": "Updated Interp",
            "image_updates": [
                {
                    "image_id": self.image1.id,
                    "category": "复查-血常规"
                }
            ]
        }
        
        request = self.factory.post(
            f'/doctor/workspace/patient/{self.patient.id}/report/{self.event1.id}/update',
            data=json.dumps(payload),
            content_type='application/json'
        )
        request.user = self.doctor_user
        
        response = patient_report_update(request, self.patient.id, self.event1.id)
        self.assertEqual(response.status_code, 200)
        
        # Verify DB updates
        self.event1.refresh_from_db()
        self.image1.refresh_from_db()
        
        self.assertEqual(self.event1.event_type, 3) # 复查
        self.assertEqual(self.event1.interpretation, "Updated Interp")
        self.assertEqual(self.image1.record_type, 3)
        self.assertEqual(self.image1.checkup_item, self.checkup_item)

    def test_create_and_refresh_flow(self):
        """测试新增记录成功后页面数据是否自动更新"""
        from django.core.files.uploadedfile import SimpleUploadedFile
        from web_doctor.views.home import create_checkup_record

        # 1. 模拟文件上传
        file_content = b"fake_image_content"
        file = SimpleUploadedFile("test_upload.jpg", file_content, content_type="image/jpeg")
        
        # 构造 POST 数据
        payload = {
            "record_type": "门诊",
            "report_date": "2025-01-03",
            "hospital": "Test Hospital",
            "remarks": "Test Remarks",
            "file_metadata": json.dumps([{
                "name": "test_upload.jpg",
                "category": "门诊",
                "subcategory": ""
            }]),
            "files[]": [file]
        }
        
        # 2. 调用创建接口
        request = self.factory.post(
            f'/doctor/workspace/patient/{self.patient.id}/checkup/create/',
            data=payload
        )
        request.user = self.doctor_user
        
        # 确保 request.user 正确关联 DoctorProfile
        # 实际上 request.user 是 User 实例，通过 user.doctor_profile 访问
        
        response = create_checkup_record(request, self.patient.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["status"], "success")
        
        # 3. 模拟刷新 (调用 handle_reports_history_section)
        refresh_request = self.factory.get('/doctor/workspace/reports?tab=records')
        refresh_request.user = self.doctor_user
        
        context = {"patient": self.patient}
        handle_reports_history_section(refresh_request, context)
        
        reports = context.get("reports_page").object_list
        
        # 4. 验证新记录是否存在
        # 原有2条，新增1条，共3条
        self.assertEqual(len(reports), 3)
        
        new_report = next((r for r in reports if r["date"] == date(2025, 1, 3)), None)
        self.assertIsNotNone(new_report)
        self.assertEqual(new_report["record_type"], "门诊")
        self.assertEqual(new_report["interpretation"], "Test Remarks")

    def test_create_consultation_record_flow(self):
        """测试使用新的 create_consultation_record 接口新增记录"""
        from django.core.files.uploadedfile import SimpleUploadedFile

        # 1. 模拟文件上传
        file_content = b"fake_image_content_new"
        file = SimpleUploadedFile("test_upload_new.jpg", file_content, content_type="image/jpeg")
        
        # 构造 POST 数据
        payload = {
            "record_type": "住院",
            "report_date": "2025-01-04",
            "hospital": "New Hospital",
            "remarks": "New Remarks",
            "file_metadata": json.dumps([{
                "name": "test_upload_new.jpg",
                "category": "住院",
                "subcategory": ""
            }]),
            "files[]": [file]
        }
        
        # 2. 调用新创建接口
        request = self.factory.post(
            f'/doctor/workspace/patient/{self.patient.id}/consultation/create/',
            data=payload
        )
        request.user = self.doctor_user
        
        response = create_consultation_record(request, self.patient.id)
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        self.assertEqual(result["status"], "success")
        self.assertIn("event_id", result)
        self.assertTrue(ClinicalEvent.objects.filter(id=result["event_id"], patient=self.patient).exists())
        
        # 3. 模拟刷新
        refresh_request = self.factory.get('/doctor/workspace/reports?tab=records')
        refresh_request.user = self.doctor_user
        
        context = {"patient": self.patient}
        handle_reports_history_section(refresh_request, context)
        
        reports = context.get("reports_page").object_list
        
        # 4. 验证新记录是否存在 (Base 2 + TestCreate 1 + This 1 = 4 if run sequentially, but tests are isolated usually)
        # Actually TestCase runs in transaction, so previous test data is rolled back.
        # So we expect 2 + 1 = 3.
        
        self.assertEqual(len(reports), 3)
        
        new_report = next((r for r in reports if r["date"] == date(2025, 1, 4)), None)
        self.assertIsNotNone(new_report)
        self.assertEqual(new_report["record_type"], "住院")
        self.assertEqual(new_report["interpretation"], "New Remarks")

    def test_uploader_display_logic(self):
        """测试上传人信息显示逻辑：始终展示患者姓名"""
        request = self.factory.get('/doctor/workspace/reports?tab=records')
        request.user = self.doctor_user
        
        context = {"patient": self.patient}
        handle_reports_history_section(request, context)
        
        reports = context.get("reports_page").object_list
        
        # 1. Check Doctor Created Event (event1)
        report1 = next(r for r in reports if r["id"] == self.event1.id)
        self.assertEqual(report1["uploader_info"]["name"], "Test Patient")
        
        # 2. Check Patient/Unknown Created Event (event2)
        report2 = next(r for r in reports if r["id"] == self.event2.id)
        self.assertEqual(report2["uploader_info"]["name"], "Test Patient")

    def test_uploader_prefers_archiver_name_for_images_area(self):
        upload = ReportUpload.objects.create(patient=self.patient, upload_source=UploadSource.DOCTOR_BACKEND)
        event = ClinicalEvent.objects.create(
            patient=self.patient,
            event_type=1,
            event_date=date(2025, 1, 3),
            created_by_doctor=self.doctor,
            archiver_name="小助理",
        )
        ReportImage.objects.create(
            upload=upload,
            image_url="http://test.com/a.jpg",
            record_type=1,
            clinical_event=event,
            report_date=event.event_date,
        )
        ReportImage.objects.create(
            upload=upload,
            image_url="http://test.com/b.jpg",
            record_type=1,
            clinical_event=event,
            report_date=event.event_date,
        )

        request = self.factory.get("/doctor/workspace/reports?tab=records")
        request.user = self.doctor_user
        context = {"patient": self.patient}
        handle_reports_history_section(request, context)

        reports = context.get("reports_page").object_list
        mapped = next(r for r in reports if r["id"] == event.id)
        self.assertEqual(mapped["archiver"], "小助理")
        self.assertEqual(mapped["uploader_info"]["name"], "Test Patient")
        self.assertEqual(mapped["image_count"], 2)

    def test_uploader_pagination_consistency(self):
        upload = ReportUpload.objects.create(patient=self.patient, upload_source=UploadSource.DOCTOR_BACKEND)
        created_ids = []
        for i in range(12):
            d = date(2025, 2, 1) + timezone.timedelta(days=i)
            event = ClinicalEvent.objects.create(
                patient=self.patient,
                event_type=1,
                event_date=d,
                created_by_doctor=self.doctor,
                archiver_name="归档人A" if i % 2 == 0 else "归档人B",
            )
            created_ids.append(event.id)
            ReportImage.objects.create(
                upload=upload,
                image_url=f"http://test.com/p{i}.jpg",
                record_type=1,
                clinical_event=event,
                report_date=event.event_date,
            )

        request1 = self.factory.get("/doctor/workspace/reports?tab=records&records_page=1")
        request1.user = self.doctor_user
        context1 = {"patient": self.patient}
        handle_reports_history_section(request1, context1)
        page1_reports = context1["reports_page"].object_list
        self.assertEqual(context1["reports_page"].number, 1)
        for r in page1_reports:
            if r["id"] in created_ids:
                self.assertIn(r["archiver"], ("归档人A", "归档人B"))
                self.assertEqual(r["uploader_info"]["name"], "Test Patient")

        request2 = self.factory.get("/doctor/workspace/reports?tab=records&records_page=2")
        request2.user = self.doctor_user
        context2 = {"patient": self.patient}
        handle_reports_history_section(request2, context2)
        page2_reports = context2["reports_page"].object_list
        self.assertEqual(context2["reports_page"].number, 2)
        for r in page2_reports:
            if r["id"] in created_ids:
                self.assertIn(r["archiver"], ("归档人A", "归档人B"))
                self.assertEqual(r["uploader_info"]["name"], "Test Patient")
