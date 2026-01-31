from datetime import date

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from health_data.models import ClinicalEvent, ReportImage, ReportUpload, UploadSource, UploaderRole
from users import choices
from users.models import CustomUser, DoctorProfile, PatientProfile


class MobilePatientRecordsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.password = "password123"

        self.doctor_user = CustomUser.objects.create_user(
            username="doctor_mobile_records",
            phone="13800002001",
            password=self.password,
            user_type=choices.UserType.DOCTOR,
        )
        self.doctor_profile = DoctorProfile.objects.create(
            user=self.doctor_user,
            name="Dr Records",
            title="主任医师",
            hospital="测试医院",
            department="测试科室",
        )

        patient_user = CustomUser.objects.create_user(
            username="patient_mobile_records",
            phone="13900002001",
            password=self.password,
            user_type=choices.UserType.PATIENT,
            wx_openid="openid_patient_mobile_records",
        )
        self.patient = PatientProfile.objects.create(
            user=patient_user,
            phone="13900002001",
            name="患者甲",
            doctor=self.doctor_profile,
            is_active=True,
            last_active_at=timezone.now(),
        )

    def test_mobile_patient_home_records_entry_points_to_records_page(self):
        self.client.force_login(self.doctor_user)
        response = self.client.get(reverse("web_doctor:mobile_patient_home", args=[self.patient.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("web_doctor:mobile_patient_records", args=[self.patient.id]))

    def test_records_page_renders_empty_state(self):
        self.client.force_login(self.doctor_user)
        response = self.client.get(reverse("web_doctor:mobile_patient_records", args=[self.patient.id]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "web_doctor/mobile/patient_records.html")
        self.assertContains(response, "暂无诊疗记录")

    def test_records_page_loads_data_and_maps_images(self):
        event = ClinicalEvent.objects.create(
            patient=self.patient,
            event_date=date(2026, 1, 1),
            event_type=int(ReportImage.RecordType.OUTPATIENT),
            interpretation="记录解读内容",
            created_by_doctor=self.doctor_profile,
            archiver_name="张主任",
        )
        upload = ReportUpload.objects.create(
            patient=self.patient,
            upload_source=UploadSource.PERSONAL_CENTER,
            uploader=self.patient.user,
            uploader_role=UploaderRole.PATIENT,
        )
        ReportImage.objects.create(
            upload=upload,
            image_url="https://example.com/report-1.jpg",
            record_type=int(ReportImage.RecordType.OUTPATIENT),
            report_date=date(2026, 1, 1),
            clinical_event=event,
            archived_by=self.doctor_profile,
            archived_at=timezone.now(),
        )

        self.client.force_login(self.doctor_user)
        response = self.client.get(reverse("web_doctor:mobile_patient_records", args=[self.patient.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "记录解读内容")
        self.assertContains(response, "https://example.com/report-1.jpg")
        self.assertContains(response, "门诊")

    def test_records_page_pagination_boundary(self):
        for idx in range(11):
            ClinicalEvent.objects.create(
                patient=self.patient,
                event_date=date(2026, 1, 1),
                event_type=int(ReportImage.RecordType.OUTPATIENT),
                interpretation=f"记录{idx}",
                created_by_doctor=self.doctor_profile,
                archiver_name="张主任",
            )

        self.client.force_login(self.doctor_user)
        url = reverse("web_doctor:mobile_patient_records", args=[self.patient.id])

        response_page_1 = self.client.get(url, {"records_page": 1})
        response_page_2 = self.client.get(url, {"records_page": 2})

        self.assertEqual(response_page_1.status_code, 200)
        self.assertEqual(response_page_2.status_code, 200)
        self.assertTrue(len(response_page_1.context["reports_page"]) <= 10)
        self.assertTrue(len(response_page_2.context["reports_page"]) <= 10)

    def test_records_page_invalid_page_param_falls_back(self):
        ClinicalEvent.objects.create(
            patient=self.patient,
            event_date=date(2026, 1, 1),
            event_type=int(ReportImage.RecordType.OUTPATIENT),
            interpretation="记录A",
            created_by_doctor=self.doctor_profile,
            archiver_name="张主任",
        )

        self.client.force_login(self.doctor_user)
        response = self.client.get(
            reverse("web_doctor:mobile_patient_records", args=[self.patient.id]),
            {"records_page": "bad"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "记录A")

    def test_records_page_denies_unrelated_doctor(self):
        other_doctor_user = CustomUser.objects.create_user(
            username="doctor_mobile_records_other",
            phone="13800002002",
            password=self.password,
            user_type=choices.UserType.DOCTOR,
        )
        DoctorProfile.objects.create(
            user=other_doctor_user,
            name="Other Doctor",
            title="主治医师",
            hospital="测试医院",
            department="测试科室",
        )

        self.client.force_login(other_doctor_user)
        response = self.client.get(reverse("web_doctor:mobile_patient_records", args=[self.patient.id]))
        self.assertEqual(response.status_code, 404)

    def test_records_page_forbidden_for_sales(self):
        sales_user = CustomUser.objects.create_user(
            username="sales_mobile_records",
            phone="13800002003",
            password=self.password,
            user_type=choices.UserType.SALES,
        )
        self.client.force_login(sales_user)
        response = self.client.get(reverse("web_doctor:mobile_patient_records", args=[self.patient.id]))
        self.assertEqual(response.status_code, 403)
