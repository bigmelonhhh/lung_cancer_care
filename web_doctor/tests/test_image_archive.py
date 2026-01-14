
import json
from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from web_doctor.views.reports_history_data import batch_archive_images, get_mock_archives_data, _init_mock_data
from users.models import DoctorProfile, PatientProfile

from users import choices

User = get_user_model()

class ImageArchiveTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        
        # Create a doctor user
        self.user = User.objects.create_user(
            username='doctor', 
            password='password',
            user_type=choices.UserType.DOCTOR,
            phone="13800000000"
        )
        self.doctor_profile = DoctorProfile.objects.create(user=self.user, name='Test Doctor')
        
        # Create a patient
        self.patient_user = User.objects.create_user(
            username='patient', 
            user_type=choices.UserType.PATIENT,
            wx_openid="test_openid"
        )
        self.patient = PatientProfile.objects.create(user=self.patient_user, name='Test Patient')
        
        # Initialize mock data
        _init_mock_data()
        
    def test_batch_archive_images_group_edit(self):
        # Get a mock report and its images
        reports = get_mock_archives_data()
        report = reports[0]
        image1 = report['images'][0]
        image2 = report['images'][1] if len(report['images']) > 1 else None
        
        updates = [
            {
                "image_id": image1['id'],
                "category": "门诊",
                "report_date": "2023-01-01"
            }
        ]
        
        if image2:
            updates.append({
                "image_id": image2['id'],
                "category": "复查-CT",
                "report_date": "2023-01-02"
            })
            
        payload = {"updates": updates}
        
        request = self.factory.post(
            f'/doctor/workspace/patient/{self.patient.id}/reports/archive/',
            data=json.dumps(payload),
            content_type='application/json'
        )
        request.user = self.user
        
        response = batch_archive_images(request, self.patient.id)
        
        self.assertEqual(response.status_code, 200)
        
        # Verify data update
        updated_reports = get_mock_archives_data()
        updated_report = next(r for r in updated_reports if r['id'] == report['id'])
        
        updated_img1 = next(img for img in updated_report['images'] if img['id'] == image1['id'])
        self.assertEqual(updated_img1['category'], "门诊")
        self.assertEqual(updated_img1['report_date'], "2023-01-01")
        
        if image2:
            updated_img2 = next(img for img in updated_report['images'] if img['id'] == image2['id'])
            self.assertEqual(updated_img2['category'], "复查-CT")
            self.assertEqual(updated_img2['report_date'], "2023-01-02")
