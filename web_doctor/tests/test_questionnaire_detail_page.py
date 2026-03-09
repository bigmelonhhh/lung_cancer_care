from datetime import date

from django.test import TestCase
from django.urls import reverse

from users import choices
from users.models import CustomUser, PatientProfile


class QuestionnaireDetailPageTests(TestCase):
    def setUp(self):
        self.doctor = CustomUser.objects.create_user(
            username="doctor_questionnaire_ui",
            password="password123",
            phone="13800009921",
            user_type=choices.UserType.DOCTOR,
        )
        self.patient = PatientProfile.objects.create(
            phone="13900009921",
            name="问卷测试患者",
            birth_date=date(1980, 1, 1),
        )
        self.url = reverse("web_doctor:questionnaire_detail", args=[self.patient.id])

    def test_questionnaire_detail_page_contains_core_ui_elements(self):
        self.client.force_login(self.doctor)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response, "web_doctor/partials/indicators/questionnaire_detail.html"
        )
        self.assertContains(response, "随访问卷详情")
        self.assertContains(response, "返回图表")
        self.assertContains(response, 'id="sidebar-container"', html=False)
        self.assertContains(response, 'id="detail-container"', html=False)
        self.assertContains(response, "历史记录")
        self.assertContains(response, "暂无历史记录")
