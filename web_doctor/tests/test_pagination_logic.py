from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from django.utils import timezone
from users.models import PatientProfile, DoctorProfile
from health_data.models import ReportUpload, ReportImage, UploadSource
from health_data.services.report_service import ReportUploadService
from web_doctor.views.reports_history_data import _get_archives_data
from django.core.paginator import Page

User = get_user_model()

class PaginationLogicTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='test_user', user_type=1, wx_openid='test_openid_123')
        self.patient = PatientProfile.objects.create(user=self.user, name="Test Patient")
        
        # Create 15 uploads to test pagination (page_size=10)
        self.uploads = []
        for i in range(15):
            upload = ReportUpload.objects.create(
                patient=self.patient,
                upload_source=UploadSource.PERSONAL_CENTER
            )
            # Update created_at manually as auto_now_add prevents setting it in create()
            upload.created_at = timezone.now() - timezone.timedelta(days=i)
            upload.save()
            
            ReportImage.objects.create(upload=upload, image_url=f"http://test.com/{i}.jpg")
            self.uploads.append(upload)

    def test_get_archives_data_pagination(self):
        """
        Test that _get_archives_data supports pagination and returns correct structure.
        """
        # Test Page 1 (default size 10)
        archives_list, page_obj = _get_archives_data(self.patient, page=1, page_size=10)
        
        self.assertIsInstance(page_obj, Page)
        self.assertEqual(len(page_obj.object_list), 10)
        self.assertTrue(page_obj.has_next())
        self.assertEqual(page_obj.paginator.count, 15)
        self.assertEqual(len(archives_list), 10) # 10 uploads -> 10 groups (different dates)
        
        # Test Page 2
        archives_list_2, page_obj_2 = _get_archives_data(self.patient, page=2, page_size=10)
        self.assertEqual(len(page_obj_2.object_list), 5)
        self.assertFalse(page_obj_2.has_next())
        self.assertEqual(len(archives_list_2), 5)

    def test_get_archives_data_custom_page_size(self):
        """
        Test custom page size.
        """
        archives_list, page_obj = _get_archives_data(self.patient, page=1, page_size=5)
        self.assertEqual(len(page_obj.object_list), 5)
        self.assertEqual(page_obj.paginator.num_pages, 3)

    def test_prefetch_behavior(self):
        """
        Ensure prefetch logic doesn't crash.
        """
        archives_list, page_obj = _get_archives_data(self.patient, page=1, page_size=10)
        # Just accessing the data to ensure it was loaded correctly
        first_group = archives_list[0]
        self.assertIn('images', first_group)
        self.assertTrue(len(first_group['images']) > 0)
