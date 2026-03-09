from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from users.models import DoctorProfile, PatientProfile

User = get_user_model()


class MobileReviewRecordDetailPageTests(TestCase):
    def setUp(self):
        self.doctor_user = User.objects.create_user(
            username="doc_review_detail_page",
            password="password",
            user_type=2,
            phone="13900139061",
        )
        self.doctor_profile = DoctorProfile.objects.create(
            user=self.doctor_user, name="Dr. Review"
        )
        self.doctor_user.doctor_profile = self.doctor_profile
        self.doctor_user.save()

        self.patient = PatientProfile.objects.create(
            name="患者复查",
            phone="13800138261",
            doctor=self.doctor_profile,
        )

    def test_review_record_detail_page_contains_core_ui_elements(self):
        self.client.force_login(self.doctor_user)
        url = reverse("web_doctor:mobile_review_record_detail")
        response = self.client.get(
            f"{url}?patient_id={self.patient.id}&category_code=ct&title=复查详情"
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "web_doctor/mobile/review_record_detail.html")
        self.assertContains(response, "复查详情")
        self.assertContains(response, 'id="rrd-month-picker"')
        self.assertContains(response, 'id="rrd-scroll"')
        self.assertContains(response, f'data-patient-id="{self.patient.id}"')
        self.assertContains(response, 'id="rrd-virtual-inner"')

