from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from django.utils import timezone
from users.models import PatientProfile, DoctorProfile
from health_data.models import ReportUpload, ReportImage, UploadSource
from health_data.services.report_service import ReportUploadService
from web_doctor.views.home import build_home_context

User = get_user_model()

class ReportConsistencyTest(TestCase):
    def setUp(self):
        # Create users
        self.patient_user = User.objects.create_user(username='patient', user_type=1, wx_openid='test_openid')
        self.doctor_user = User.objects.create_user(username='doctor', user_type=2, phone='13800000000')
        
        # Create profiles
        self.patient = PatientProfile.objects.create(user=self.patient_user, name="Test Patient")
        self.doctor = DoctorProfile.objects.create(user=self.doctor_user, name="Test Doctor")
        
        # Create uploads
        # 1. Personal Center Upload (Patient sees, Doctor should see)
        self.upload_personal = ReportUpload.objects.create(
            patient=self.patient,
            upload_source=UploadSource.PERSONAL_CENTER,
            created_at=timezone.now() - timezone.timedelta(days=1)
        )
        ReportImage.objects.create(upload=self.upload_personal, image_url="http://p.com/1.jpg")

        # 2. Doctor Backend Upload (Patient NOT see, Doctor currently sees)
        self.upload_doctor = ReportUpload.objects.create(
            patient=self.patient,
            upload_source=UploadSource.DOCTOR_BACKEND,
            created_at=timezone.now()
        )
        ReportImage.objects.create(upload=self.upload_doctor, image_url="http://d.com/1.jpg")

    def test_doctor_view_consistency_with_patient(self):
        """
        Verify that Doctor view now filters by PERSONAL_CENTER to match Patient view.
        """
        context = build_home_context(self.patient)
        latest_reports = context['latest_reports']
        
        # After fix: Doctor sees the PERSONAL_CENTER upload (even though DOCTOR_BACKEND is newer)
        # Because we filtered by source
        self.assertIn("http://p.com/1.jpg", latest_reports['images'])
        self.assertNotIn("http://d.com/1.jpg", latest_reports['images'])

    def test_multiple_uploads_same_day(self):
        """
        Verify that if patient uploads multiple times on the same day,
        Doctor view aggregates them (showing all images), matching Patient view logic.
        """
        # Create another upload on the same day as upload_personal (created in setUp)
        # upload_personal was created at timezone.now() - 1 day
        same_day = self.upload_personal.created_at
        
        upload_2 = ReportUpload.objects.create(
            patient=self.patient,
            upload_source=UploadSource.PERSONAL_CENTER,
            created_at=same_day + timezone.timedelta(hours=1)
        )
        ReportImage.objects.create(upload=upload_2, image_url="http://p.com/2.jpg")
        
        # Now we have two uploads on 'same_day'.
        # upload_2 is newer (hours=1 later).
        
        context = build_home_context(self.patient)
        latest_reports = context['latest_reports']
        
        # Doctor view currently only fetches .first() -> upload_2
        # So it likely only contains 2.jpg
        # We WANT it to contain BOTH 1.jpg and 2.jpg because they are same day.
        
        images = latest_reports['images']
        self.assertIn("http://p.com/2.jpg", images)
        self.assertIn("http://p.com/1.jpg", images, "Should include images from earlier upload on same day")
        
    def test_patient_view_logic_restriction(self):
        """
        Simulate Patient view logic (from my_report.py)
        """
        patient_uploads = ReportUploadService.list_uploads(
            patient=self.patient,
            upload_source=UploadSource.PERSONAL_CENTER
        )
        
        # Patient only sees PERSONAL_CENTER
        self.assertEqual(patient_uploads.count(), 1)
        self.assertEqual(patient_uploads.first(), self.upload_personal)
