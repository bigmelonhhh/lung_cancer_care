from django.test import TestCase, RequestFactory
from django.template.loader import render_to_string
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from datetime import date
from decimal import Decimal
from web_doctor.views.reports_history_data import (
    create_consultation_record,
    handle_reports_history_section,
    patient_report_update,
)
from health_data.models import CheckupResultValue, ClinicalEvent, ReportImage, ReportUpload, UploadSource
from core.models import CheckupFieldMapping, CheckupLibrary, StandardField, StandardFieldValueType
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
        self.client.force_login(self.doctor_user)
        
        # Patient
        self.patient_user = User.objects.create_user(
            username='patient', 
            user_type=choices.UserType.PATIENT,
            wx_openid="test_openid"
        )
        self.patient = PatientProfile.objects.create(user=self.patient_user, name='Test Patient')
        
        # Checkup Library
        self.checkup_item = CheckupLibrary.objects.create(name="血常规")
        self.standard_field = StandardField.objects.create(
            local_code="WBC_CONSULTATION",
            chinese_name="白细胞",
            value_type=StandardFieldValueType.DECIMAL,
            default_unit="10^9/L",
        )
        CheckupFieldMapping.objects.create(
            checkup_item=self.checkup_item,
            standard_field=self.standard_field,
            sort_order=100,
        )
        
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

    def test_report_image_metrics_api_returns_structured_rows_with_previous_value(self):
        previous_upload = ReportUpload.objects.create(patient=self.patient, upload_source=UploadSource.DOCTOR_BACKEND)
        previous_image = ReportImage.objects.create(
            upload=previous_upload,
            image_url="http://test.com/prev.jpg",
            record_type=3,
            checkup_item=self.checkup_item,
            clinical_event=self.event2,
            report_date=date(2025, 1, 1),
        )
        same_day_image = ReportImage.objects.create(
            upload=previous_upload,
            image_url="http://test.com/same-day.jpg",
            record_type=3,
            checkup_item=self.checkup_item,
            clinical_event=self.event2,
            report_date=self.image2.report_date,
        )
        CheckupResultValue.objects.create(
            patient=self.patient,
            report_image=previous_image,
            checkup_item=self.checkup_item,
            standard_field=self.standard_field,
            report_date=previous_image.report_date,
            raw_name="白细胞",
            normalized_name="白细胞",
            raw_value="4.8",
            value_numeric=Decimal("4.8"),
            unit="10^9/L",
            lower_bound=Decimal("3.5"),
            upper_bound=Decimal("9.5"),
            range_text="3.5-9.5",
        )
        CheckupResultValue.objects.create(
            patient=self.patient,
            report_image=same_day_image,
            checkup_item=self.checkup_item,
            standard_field=self.standard_field,
            report_date=same_day_image.report_date,
            raw_name="白细胞",
            normalized_name="白细胞",
            raw_value="5.1",
            value_numeric=Decimal("5.1"),
        )
        CheckupResultValue.objects.create(
            patient=self.patient,
            report_image=self.image2,
            checkup_item=self.checkup_item,
            standard_field=self.standard_field,
            report_date=self.image2.report_date,
            raw_name="白细胞",
            normalized_name="白细胞",
            raw_value="6.3",
            value_numeric=Decimal("6.3"),
            unit="10^9/L",
            lower_bound=Decimal("3.5"),
            upper_bound=Decimal("9.5"),
            range_text="3.5-9.5",
        )

        response = self.client.get(
            reverse("web_doctor:patient_report_image_metrics", args=[self.patient.id, self.image2.id])
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["title"], "复查-血常规")
        self.assertEqual(payload["report_date"], "2025-01-02")
        self.assertEqual(len(payload["rows"]), 1)
        row = payload["rows"][0]
        self.assertEqual(row["field_code"], "WBC_CONSULTATION")
        self.assertEqual(row["current_value_display"], "6.3")
        self.assertEqual(row["previous_value_display"], "4.8")
        self.assertEqual(row["delta_display"], "+1.5")

    def test_report_image_metrics_api_returns_404_for_other_patient_image(self):
        other_patient = PatientProfile.objects.create(name="Other", phone="13800009999")
        other_upload = ReportUpload.objects.create(patient=other_patient, upload_source=UploadSource.DOCTOR_BACKEND)
        other_event = ClinicalEvent.objects.create(patient=other_patient, event_type=3, event_date=date(2025, 1, 5))
        other_image = ReportImage.objects.create(
            upload=other_upload,
            image_url="http://test.com/other.jpg",
            record_type=3,
            checkup_item=self.checkup_item,
            clinical_event=other_event,
            report_date=date(2025, 1, 5),
        )

        response = self.client.get(
            reverse("web_doctor:patient_report_image_metrics", args=[self.patient.id, other_image.id])
        )

        self.assertEqual(response.status_code, 404)

    def test_consultation_records_detail_fragment_uses_real_metrics_endpoint_and_hides_mock_controls(self):
        request = self.factory.get('/doctor/workspace/reports?tab=records')
        request.user = self.doctor_user
        context = {"patient": self.patient}
        template_name = handle_reports_history_section(request, context)
        rendered = render_to_string(template_name, context, request=request)

        self.assertNotIn(
            reverse("web_doctor:patient_report_image_metrics", args=[self.patient.id, self.image2.id]),
            rendered,
        )
        self.assertNotIn(
            reverse("web_doctor:patient_report_image_metrics", args=[self.patient.id, self.image1.id]),
            rendered,
        )
        self.assertNotIn("getMockMetricData", rendered)
        self.assertNotIn("新增检测指标", rendered)
        self.assertNotIn("编辑指标配置", rendered)

        detail_response = self.client.get(
            reverse("web_doctor:patient_report_detail", args=[self.patient.id, self.event2.id])
        )
        self.assertEqual(detail_response.status_code, 200)
        detail_html = detail_response.content.decode("utf-8")
        self.assertIn(
            reverse("web_doctor:patient_report_image_metrics", args=[self.patient.id, self.image2.id]),
            detail_html,
        )
        self.assertNotIn(
            reverse("web_doctor:patient_report_image_metrics", args=[self.patient.id, self.image1.id]),
            detail_html,
        )
        self.assertIn("指标数据加载中...", detail_html)
        self.assertIn('x-text="metricError"', detail_html)
        self.assertIn("typeof getMetricCellClass === 'function'", detail_html)
        self.assertIn(
            "getMetricCellClass(row, { value: row.previous_value_display, allowPlaceholderNeutral: true })",
            detail_html,
        )
        self.assertIn(
            "getMetricCellClass(row, { value: row.delta_display, allowPlaceholderNeutral: true })",
            detail_html,
        )
        self.assertIn("bg-rose-100 text-rose-700", detail_html)
        self.assertIn("bg-sky-100 text-sky-700", detail_html)
        self.assertNotIn("text-emerald-600", detail_html)
        self.assertNotIn("row.delta_direction === 'up'", detail_html)
