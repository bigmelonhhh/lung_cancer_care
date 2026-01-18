from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import date
from web_doctor.views.reports_history_data import handle_reports_history_section, patient_report_update
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
