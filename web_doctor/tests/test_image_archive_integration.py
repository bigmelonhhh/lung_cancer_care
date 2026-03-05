
import json
from datetime import date, timedelta
from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.utils import timezone

from users.models import AssistantProfile, DoctorProfile, PatientProfile
from users import choices
from health_data.models import ReportUpload, ReportImage, ClinicalEvent, UploadSource
from core.models import CheckupLibrary, DailyTask, choices as core_choices
from web_doctor.views.reports_history_data import handle_reports_history_section, batch_archive_images

from django.core.exceptions import PermissionDenied

User = get_user_model()

class ImageArchiveIntegrationTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        
        # 1. Setup Users
        self.doctor_user = User.objects.create_user(
            username='doctor', 
            user_type=choices.UserType.DOCTOR,
            phone="13800000000"
        )
        self.doctor_profile = DoctorProfile.objects.create(user=self.doctor_user, name='Dr. Test')

        self.assistant_user = User.objects.create_user(
            username="assistant",
            user_type=choices.UserType.ASSISTANT,
            phone="13800000001",
        )
        self.assistant_profile = AssistantProfile.objects.create(user=self.assistant_user, name="小桃妖")
        self.assistant_profile.doctors.add(self.doctor_profile)
        
        self.patient_user = User.objects.create_user(
            username='patient', 
            user_type=choices.UserType.PATIENT,
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
        # Fix created_at for consistent testing
        fixed_time = timezone.datetime(2023, 1, 1, 0, 0, 0, tzinfo=timezone.get_current_timezone())
        ReportUpload.objects.filter(pk=self.upload.pk).update(created_at=fixed_time)
        
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
        
        # archives_page changed to archives_list in view
        archives_list = context.get('archives_list')
        self.assertIsNotNone(archives_list)
        
        # Check if grouping logic works (2 images, same date -> 1 group)
        self.assertEqual(len(archives_list), 1)
        
        group_data = archives_list[0]
        self.assertEqual(group_data['date'], "2023-01-01 00:00:00")
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
        dt2 = timezone.datetime(2023, 1, 2, 0, 0, 0, tzinfo=timezone.get_current_timezone())
        ReportUpload.objects.filter(pk=upload2.pk).update(created_at=dt2)
        
        ReportImage.objects.create(
            upload=upload2,
            image_url="http://test.com/3.jpg",
            report_date=date(2023, 1, 2)
        )
        
        request = self.factory.get('/?tab=images')
        request.user = self.doctor_user
        
        context = {"patient": self.patient}
        handle_reports_history_section(request, context)
        
        archives_list = context.get('archives_list')
        
        # Should have 2 groups now (2023-01-02 and 2023-01-01)
        self.assertEqual(len(archives_list), 2)
        
        # Sort order is reverse date (newest first)
        group1 = archives_list[0]
        self.assertEqual(group1['date'], "2023-01-02 00:00:00")
        self.assertEqual(group1['image_count'], 1)
        
        group2 = archives_list[1]
        self.assertEqual(group2['date'], "2023-01-01 00:00:00")
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
        
        updated_archives = context['archives_list'][0]
        self.assertTrue(updated_archives['is_archived'])
        self.assertEqual(updated_archives['archiver'], "Dr. Test")
        
        img1_display = next(img for img in updated_archives['images'] if img['id'] == self.img1.id)
        self.assertEqual(img1_display['category'], "门诊")
        
        img2_display = next(img for img in updated_archives['images'] if img['id'] == self.img2.id)
        self.assertEqual(img2_display['category'], "复查-胸部CT")

    def test_batch_archive_flow_assistant_sets_archiver_name(self):
        payload = {
            "updates": [
                {
                    "image_id": self.img1.id,
                    "category": "门诊",
                    "report_date": "2023-05-01",
                }
            ]
        }
        request = self.factory.post(
            f"/doctor/workspace/patient/{self.patient.id}/reports/archive/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        request.user = self.assistant_user

        response = batch_archive_images(request, self.patient.id)
        self.assertEqual(response.status_code, 200)

        self.img1.refresh_from_db()
        self.assertIsNotNone(self.img1.clinical_event_id)
        event = ClinicalEvent.objects.get(id=self.img1.clinical_event_id)
        self.assertEqual(event.archiver_name, "小桃妖")

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
        
        self.assertEqual(response.status_code, 400)
        self.assertIn("报告日期格式错误".encode("utf-8"), response.content)

    def test_archive_permission_denied(self):
        """
        Integration Test: Verify permission denied for non-doctor users.
        """
        payload = {
            "updates": [
                {
                    "image_id": self.img1.id,
                    "category": "门诊",
                    "report_date": "2023-05-01"
                }
            ]
        }
        
        request = self.factory.post(
            f'/doctor/workspace/patient/{self.patient.id}/reports/archive/',
            data=json.dumps(payload),
            content_type='application/json'
        )
        # Use patient user instead of doctor
        request.user = self.patient_user
        
        # Check_doctor_or_assistant decorator should redirect or return 403/302 depending on implementation
        # Usually redirects to login or returns 403.
        # The decorator raises PermissionDenied exception which Django handles as 403.
        # But in unit test calling view directly, we catch exception.
        # The previous attempt failed because response assignment was outside the assertRaises block
        with self.assertRaises(PermissionDenied):
             batch_archive_images(request, self.patient.id)

    def test_archive_empty_payload(self):
        """
        Integration Test: Verify handling of empty payload.
        """
        payload = {"updates": []}
        
        request = self.factory.post(
            '/archive/',
            data=json.dumps(payload),
            content_type='application/json'
        )
        request.user = self.doctor_user
        
        response = batch_archive_images(request, self.patient.id)
        self.assertEqual(response.status_code, 400)
        self.assertIn(b'\xe5\x8f\x82\xe6\x95\xb0\xe4\xb8\x8d\xe5\xae\x8c\xe6\x95\xb4', response.content) # "参数不完整"

    def test_archive_partial_invalid(self):
        """
        Integration Test: Verify behavior when some updates are invalid.
        """
        payload = {
            "updates": [
                {
                    "image_id": self.img1.id,
                    "category": "门诊",
                    "report_date": "2023-05-01"
                },
                {
                    "image_id": 99999, # Invalid ID
                    "category": "复查-胸部CT",
                    "report_date": "2023-05-02"
                }
            ]
        }
        
        request = self.factory.post(
            '/archive/',
            data=json.dumps(payload),
            content_type='application/json'
        )
        request.user = self.doctor_user
        
        # Currently, if service.archive_images is called, it validates IDs.
        # ReportArchiveService.archive_images logic:
        # image_map = {img.id: img for img in images}
        # if len(image_map) != len(image_ids): raise ValidationError("存在无效的图片 ID。")
        # So it should fail completely.
        
        response = batch_archive_images(request, self.patient.id)
        self.assertEqual(response.status_code, 400)
        self.assertIn(b'\xe5\xbd\x92\xe6\xa1\xa3\xe5\xa4\xb1\xe8\xb4\xa5', response.content) # "归档失败"

    def test_archive_filtering(self):
        """
        Integration Test: Verify date filtering logic.
        """
        # Create test data
        u1 = ReportUpload.objects.create(patient=self.patient)
        # Update created_at to Jan 1
        dt1 = timezone.datetime(2023, 1, 1, 10, 0, 0, tzinfo=timezone.get_current_timezone())
        ReportUpload.objects.filter(pk=u1.pk).update(created_at=dt1)
        ReportImage.objects.create(upload=u1, image_url="u1.jpg", record_type=ReportImage.RecordType.OUTPATIENT, report_date=date(2023, 1, 1))
        
        u2 = ReportUpload.objects.create(patient=self.patient)
        # Update created_at to Feb 1
        dt2 = timezone.datetime(2023, 2, 1, 10, 0, 0, tzinfo=timezone.get_current_timezone())
        ReportUpload.objects.filter(pk=u2.pk).update(created_at=dt2)
        ReportImage.objects.create(upload=u2, image_url="u2.jpg", record_type=ReportImage.RecordType.INPATIENT, report_date=date(2023, 2, 1))
        
        request = self.factory.get('/?tab=images')
        request.user = self.doctor_user
        context = {"patient": self.patient}
        
        # Case 1: Filter by Date
        request.GET = {"tab": "images", "startDate": "2023-01-01", "endDate": "2023-01-31"}
        handle_reports_history_section(request, context)
        archives = context['archives_list']
        self.assertEqual(len(archives), 1)

        # Category filtering has been removed; passing category should not affect results.
        request.GET = {"tab": "images", "category": "住院"}
        handle_reports_history_section(request, context)
        archives = context['archives_list']
        self.assertEqual(len(archives), 2)

    def test_checkup_plan_unarchived_badge_visible_and_hidden_after_archive(self):
        # 先将 setUp 中个人中心图片归档，避免干扰“未归档”文案计数
        existing_event = ClinicalEvent.objects.create(
            patient=self.patient,
            event_date=date(2023, 1, 1),
            event_type=ReportImage.RecordType.OUTPATIENT,
            created_by_doctor=self.doctor_profile,
            archiver_name="Dr. Test",
        )
        ReportImage.objects.filter(id__in=[self.img1.id, self.img2.id]).update(
            clinical_event=existing_event,
            record_type=ReportImage.RecordType.OUTPATIENT,
            report_date=date(2023, 1, 1),
        )

        checkup_task = DailyTask.objects.create(
            patient=self.patient,
            task_date=date(2023, 1, 3),
            task_type=core_choices.PlanItemCategory.CHECKUP,
            title="复查任务-胸部CT",
            interaction_payload={"checkup_id": self.ct_checkup.id},
        )
        upload = ReportUpload.objects.create(
            patient=self.patient,
            upload_source=UploadSource.CHECKUP_PLAN,
            related_task=checkup_task,
        )
        upload_time = timezone.datetime(2023, 1, 3, 8, 0, 0, tzinfo=timezone.get_current_timezone())
        ReportUpload.objects.filter(pk=upload.pk).update(created_at=upload_time)
        plan_img = ReportImage.objects.create(
            upload=upload,
            image_url="http://test.com/checkup-plan.jpg",
            record_type=ReportImage.RecordType.CHECKUP,
            report_date=date(2023, 1, 3),
        )

        request = self.factory.get('/?tab=images')
        request.user = self.doctor_user
        context = {"patient": self.patient}
        template_name = handle_reports_history_section(request, context)
        html_before = render_to_string(template_name, context=context, request=request)

        self.assertIn("复查-胸部CT", html_before)
        self.assertIn("bg-red-500 text-white text-[10px] px-2 py-0.5 rounded-br-lg", html_before)

        payload = {
            "updates": [
                {
                    "image_id": plan_img.id,
                    "category": "复查-胸部CT",
                    "report_date": "2023-01-03",
                }
            ]
        }
        request_archive = self.factory.post(
            f'/doctor/workspace/patient/{self.patient.id}/reports/archive/',
            data=json.dumps(payload),
            content_type='application/json'
        )
        request_archive.user = self.doctor_user
        response = batch_archive_images(request_archive, self.patient.id)
        self.assertEqual(response.status_code, 200)

        plan_img.refresh_from_db()
        self.assertIsNotNone(plan_img.clinical_event_id)

        context_after = {"patient": self.patient}
        template_name_after = handle_reports_history_section(request, context_after)
        html_after = render_to_string(template_name_after, context=context_after, request=request)

        self.assertIn("复查-胸部CT", html_after)
        self.assertNotIn("bg-red-500 text-white text-[10px] px-2 py-0.5 rounded-br-lg", html_after)

    def test_second_submit_ignores_archived_images_and_archives_remaining(self):
        task = DailyTask.objects.create(
            patient=self.patient,
            task_date=date(2023, 1, 5),
            task_type=core_choices.PlanItemCategory.CHECKUP,
            title="复查任务-胸部CT",
            interaction_payload={"checkup_id": self.ct_checkup.id},
        )
        upload = ReportUpload.objects.create(
            patient=self.patient,
            upload_source=UploadSource.CHECKUP_PLAN,
            related_task=task,
        )
        upload_time = timezone.datetime(2023, 1, 5, 8, 0, 0, tzinfo=timezone.get_current_timezone())
        ReportUpload.objects.filter(pk=upload.pk).update(created_at=upload_time)

        plan_imgs = [
            ReportImage.objects.create(
                upload=upload,
                image_url=f"http://test.com/checkup-plan-{idx}.jpg",
                record_type=ReportImage.RecordType.CHECKUP,
                report_date=date(2023, 1, 5),
            )
            for idx in range(4)
        ]

        first_payload = {
            "updates": [
                {
                    "image_id": plan_imgs[0].id,
                    "category": "复查-胸部CT",
                    "report_date": "2023-01-05",
                },
                {
                    "image_id": plan_imgs[1].id,
                    "category": "复查-胸部CT",
                    "report_date": "2023-01-05",
                },
            ]
        }
        req_first = self.factory.post(
            f"/doctor/workspace/patient/{self.patient.id}/reports/archive/",
            data=json.dumps(first_payload),
            content_type="application/json",
        )
        req_first.user = self.doctor_user
        first_resp = batch_archive_images(req_first, self.patient.id)
        self.assertEqual(first_resp.status_code, 200)

        for img in plan_imgs:
            img.refresh_from_db()
        self.assertIsNotNone(plan_imgs[0].clinical_event_id)
        self.assertIsNotNone(plan_imgs[1].clinical_event_id)
        self.assertIsNone(plan_imgs[2].clinical_event_id)
        self.assertIsNone(plan_imgs[3].clinical_event_id)

        # 第二次提交故意混入已归档 ID，后端应忽略并仅归档剩余未归档图片
        second_payload = {
            "updates": [
                {
                    "image_id": img.id,
                    "category": "复查-胸部CT",
                    "report_date": "2023-01-05",
                }
                for img in plan_imgs
            ]
        }
        req_second = self.factory.post(
            f"/doctor/workspace/patient/{self.patient.id}/reports/archive/",
            data=json.dumps(second_payload),
            content_type="application/json",
        )
        req_second.user = self.doctor_user
        second_resp = batch_archive_images(req_second, self.patient.id)
        self.assertEqual(second_resp.status_code, 200)

        for img in plan_imgs:
            img.refresh_from_db()
            self.assertIsNotNone(img.clinical_event_id)

        request_get = self.factory.get("/?tab=images")
        request_get.user = self.doctor_user
        context = {"patient": self.patient}
        handle_reports_history_section(request_get, context)
        all_images = []
        for group in context["archives_list"]:
            all_images.extend(group.get("images") or [])
        archived_map = {item["id"]: item["is_archived"] for item in all_images}
        for img in plan_imgs:
            self.assertTrue(archived_map.get(img.id))

    def test_all_archived_submit_returns_200_with_info_toast(self):
        payload = {
            "updates": [
                {
                    "image_id": self.img1.id,
                    "category": "门诊",
                    "report_date": "2023-05-01",
                }
            ]
        }

        req_first = self.factory.post(
            f"/doctor/workspace/patient/{self.patient.id}/reports/archive/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        req_first.user = self.doctor_user
        first_resp = batch_archive_images(req_first, self.patient.id)
        self.assertEqual(first_resp.status_code, 200)

        req_second = self.factory.post(
            f"/doctor/workspace/patient/{self.patient.id}/reports/archive/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        req_second.user = self.doctor_user
        second_resp = batch_archive_images(req_second, self.patient.id)
        self.assertEqual(second_resp.status_code, 200)
        self.assertIn("HX-Trigger", second_resp)
        trigger_payload = json.loads(second_resp["HX-Trigger"])
        self.assertEqual(trigger_payload["show-toast"]["message"], "无未归档图片需要归档")
        self.assertEqual(trigger_payload["show-toast"]["type"], "info")

        self.img1.refresh_from_db()
        self.assertIsNotNone(self.img1.clinical_event_id)
