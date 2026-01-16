
import json
import uuid
from datetime import date
from django.test import TestCase, Client
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from users.models import CustomUser, PatientProfile
from health_data.models.report_upload import ReportUpload, ReportImage, UploadSource

class MyReportTests(TestCase):
    def setUp(self):
        # Create User and Patient
        self.user = CustomUser.objects.create_user(
            username="testuser",
            password="password",
            wx_openid="test_openid"
        )
        self.patient = PatientProfile.objects.create(
            user=self.user,
            name="Test Patient",
            phone="13800000001"
        )
        
        # Log in
        self.client = Client()
        self.client.force_login(self.user)
        
        # URLs
        self.list_url = reverse('web_patient:report_list')
        self.upload_url = reverse('web_patient:report_upload')
        self.delete_url = reverse('web_patient:report_delete')

    def test_report_list_empty(self):
        """Test list view with no reports"""
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['grouped_reports']), 0)

    def test_report_list_with_data(self):
        """Test list view with reports"""
        # Create a report upload
        upload = ReportUpload.objects.create(
            patient=self.patient,
            upload_source=UploadSource.PERSONAL_CENTER
        )
        ReportImage.objects.create(
            upload=upload,
            image_url="/media/test.jpg",
            report_date=date(2023, 1, 1)
        )
        
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['grouped_reports']), 1)
        group = response.context['grouped_reports'][0]
        self.assertEqual(group['date'], date(2023, 1, 1))
        self.assertIn("/media/test.jpg", group['images'])

    def test_upload_report_success(self):
        """Test uploading a report"""
        image = SimpleUploadedFile("test.jpg", b"content", content_type="image/jpeg")
        data = {
            'report_date': '2023-01-02',
            'images': [image]
        }
        
        response = self.client.post(self.upload_url, data, follow=True) # follow redirect
        
        self.assertEqual(response.status_code, 200)
        
        # Verify DB
        self.assertEqual(ReportUpload.objects.count(), 1)
        upload = ReportUpload.objects.first()
        self.assertEqual(upload.patient, self.patient)
        self.assertEqual(upload.upload_source, UploadSource.PERSONAL_CENTER)
        
        self.assertEqual(ReportImage.objects.count(), 1)
        img = ReportImage.objects.first()
        self.assertEqual(img.upload, upload)
        self.assertEqual(img.report_date, date(2023, 1, 2))

    def test_delete_report(self):
        """Test deleting a report using Service"""
        # Create data
        upload = ReportUpload.objects.create(
            patient=self.patient,
            upload_source=UploadSource.PERSONAL_CENTER
        )
        
        # Delete
        data = {'ids': [upload.id]}
        response = self.client.post(
            self.delete_url,
            data=data,
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ReportUpload.objects.count(), 0)

    def test_delete_report_permission(self):
        """Test deleting another patient's report"""
        other_user = CustomUser.objects.create_user(
            username="other", 
            password="password",
            wx_openid="other_openid"
        )
        other_patient = PatientProfile.objects.create(user=other_user, name="Other", phone="13800000002")
        
        other_upload = ReportUpload.objects.create(patient=other_patient)
        
        data = {'ids': [other_upload.id]}
        response = self.client.post(
            self.delete_url,
            data=data,
            content_type='application/json'
        )
        
        # Should return success but not delete (filter returns empty) or error?
        # The view uses filter().delete(), so it just does nothing if not found.
        # It returns success status.
        self.assertEqual(response.status_code, 200)
        self.assertTrue(ReportUpload.objects.filter(id=other_upload.id).exists())
