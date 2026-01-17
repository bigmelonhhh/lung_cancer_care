
import json
from datetime import date, timedelta
from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from django.utils import timezone

from users.models import DoctorProfile, PatientProfile
from health_data.models import ReportUpload, ReportImage, ClinicalEvent, UploadSource
from core.models import CheckupLibrary
from web_doctor.views.reports_history_data import handle_reports_history_section, batch_archive_images

User = get_user_model()

class ImageArchiveIntegrationTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        
        # 1. Setup Users
        self.doctor_user = User.objects.create_user(
            username='doctor', 
            user_type=2,
            phone="13800000000"
        )
        self.doctor_profile = DoctorProfile.objects.create(user=self.doctor_user, name='Dr. Test')
        
        self.patient_user = User.objects.create_user(
            username='patient', 
            user_type=1,
            wx_openid="test_openid"
        )
        self.patient = PatientProfile.objects.create(user=self.patient_user, name='Test Patient')
        
        # 2. Setup Checkup Library
        self.ct_checkup = CheckupLibrary.objects.create(name="胸部CT", code="CT")
        
        # 3. Setup Initial Data (Unarchived Images)
        self.upload = ReportUpload.objects.create(
            patient=self.patient,
            upload_source=UploadSource.PERSONAL_CENTER
        )
        self.img1 = ReportImage.objects.create(
            upload=self.upload,
            image_url="http://test.com/1.jpg",
            report_date=date(2023, 1, 1)
        )
        self.img2 = ReportImage.objects.create(
            upload=self.upload,
            image_url="http://test.com/2.jpg",
            report_date=date(2023, 1, 1)
        )

    def test_display_archives_data(self):
        """
        Integration Test: Verify handle_reports_history_section returns correct real data structure.
        """
        request = self.factory.get('/?tab=images')
        request.user = self.doctor_user
        
        context = {"patient": self.patient}
        handle_reports_history_section(request, context)
        
        archives_page = context.get('archives_page')
        self.assertIsNotNone(archives_page)
        
        # Check if grouping logic works (2 images, same date -> 1 group)
        self.assertEqual(len(archives_page.object_list), 1)
        
        group_data = archives_page.object_list[0]
        self.assertEqual(group_data['date'], "2023-01-01")
        self.assertEqual(group_data['image_count'], 2)
        self.assertEqual(len(group_data['images']), 2)
        
        # Check image fields
        img_data = group_data['images'][0]
        self.assertEqual(img_data['id'], self.img1.id)
        self.assertEqual(img_data['url'], "http://test.com/1.jpg")
        self.assertFalse(img_data['is_archived'])
        self.assertEqual(img_data['category'], "") # Not archived yet

    def test_grouping_multiple_dates(self):
        """
        Integration Test: Verify grouping logic with different dates.
        """
        # Create another upload with a different date
        upload2 = ReportUpload.objects.create(
            patient=self.patient,
            upload_source=UploadSource.PERSONAL_CENTER
        )
        ReportImage.objects.create(
            upload=upload2,
            image_url="http://test.com/3.jpg",
            report_date=date(2023, 1, 2)
        )
        
        request = self.factory.get('/?tab=images')
        request.user = self.doctor_user
        
        context = {"patient": self.patient}
        handle_reports_history_section(request, context)
        
        archives_page = context.get('archives_page')
        
        # Should have 2 groups now (2023-01-02 and 2023-01-01)
        self.assertEqual(len(archives_page.object_list), 2)
        
        # Sort order is reverse date (newest first)
        group1 = archives_page.object_list[0]
        self.assertEqual(group1['date'], "2023-01-02")
        self.assertEqual(group1['image_count'], 1)
        
        group2 = archives_page.object_list[1]
        self.assertEqual(group2['date'], "2023-01-01")
        self.assertEqual(group2['image_count'], 2)

    def test_batch_archive_flow(self):
        """
        Integration Test: Full flow of archiving images via batch_archive_images view.
        """
        # Prepare payload simulating frontend submission
        payload = {
            "updates": [
                {
                    "image_id": self.img1.id,
                    "category": "门诊",
                    "report_date": "2023-05-01"
                },
                {
                    "image_id": self.img2.id,
                    "category": "复查-胸部CT",
                    "report_date": "2023-05-02"
                }
            ]
        }
        
        request = self.factory.post(
            f'/doctor/workspace/patient/{self.patient.id}/reports/archive/',
            data=json.dumps(payload),
            content_type='application/json'
        )
        request.user = self.doctor_user
        
        # Execute View
        response = batch_archive_images(request, self.patient.id)
        self.assertEqual(response.status_code, 200)
        
        # Verify Database Updates
        self.img1.refresh_from_db()
        self.img2.refresh_from_db()
        
        # Check Img1 (Outpatient)
        self.assertEqual(self.img1.record_type, ReportImage.RecordType.OUTPATIENT)
        self.assertEqual(str(self.img1.report_date), "2023-05-01")
        self.assertIsNotNone(self.img1.clinical_event)
        self.assertEqual(self.img1.clinical_event.event_type, ReportImage.RecordType.OUTPATIENT)
        
        # Check Img2 (Checkup)
        self.assertEqual(self.img2.record_type, ReportImage.RecordType.CHECKUP)
        self.assertEqual(self.img2.checkup_item, self.ct_checkup)
        self.assertEqual(str(self.img2.report_date), "2023-05-02")
        self.assertIsNotNone(self.img2.clinical_event)
        
        # Verify Display Logic after archiving
        context = {"patient": self.patient}
        request_get = self.factory.get('/?tab=images')
        request_get.user = self.doctor_user
        handle_reports_history_section(request_get, context)
        
        updated_archives = context['archives_page'].object_list[0]
        self.assertTrue(updated_archives['is_archived'])
        self.assertEqual(updated_archives['archiver'], "Dr. Test")
        
        img1_display = next(img for img in updated_archives['images'] if img['id'] == self.img1.id)
        self.assertEqual(img1_display['category'], "门诊")
        
        img2_display = next(img for img in updated_archives['images'] if img['id'] == self.img2.id)
        self.assertEqual(img2_display['category'], "复查-胸部CT")

    def test_archive_error_handling(self):
        """
        Integration Test: Verify error handling for invalid data.
        """
        # Payload with invalid date
        payload = {
            "updates": [
                {
                    "image_id": self.img1.id,
                    "category": "门诊",
                    "report_date": "invalid-date"
                }
            ]
        }
        
        request = self.factory.post(
            '/archive/',
            data=json.dumps(payload),
            content_type='application/json'
        )
        request.user = self.doctor_user
        
        response = batch_archive_images(request, self.patient.id)
        
        # Should return 400 because no valid updates could be parsed
        self.assertEqual(response.status_code, 400)
        self.assertIn(b'\xe6\x97\xa0\xe6\x9c\x89\xe6\x95\x88\xe6\x9b\xb4\xe6\x96\xb0\xe6\x95\xb0\xe6\x8d\xae', response.content) # "无有效更新数据" in utf-8 bytes
