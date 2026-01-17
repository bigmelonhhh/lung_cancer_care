from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from django.urls import reverse
from web_doctor.views.workspace import patient_workspace_section
from users.models import DoctorProfile, PatientProfile
from users import choices

User = get_user_model()

class ReportNavigationTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username='doctor', 
            password='password',
            user_type=choices.UserType.DOCTOR,
            phone="13800000000"
        )
        self.doctor_profile = DoctorProfile.objects.create(user=self.user, name='Test Doctor')
        
        self.patient_user = User.objects.create_user(
            username='patient', 
            user_type=choices.UserType.PATIENT,
            wx_openid="test_openid"
        )
        self.patient = PatientProfile.objects.create(user=self.patient_user, name='Test Patient', doctor=self.doctor_profile)

    def test_reports_history_tab_parameter(self):
        """
        Test that accessing reports_history with ?tab=images sets the active_tab in context.
        """
        url = reverse('web_doctor:patient_workspace_section', args=[self.patient.id, 'reports_history'])
        request = self.factory.get(url, {'tab': 'images'})
        request.user = self.user
        
        response = patient_workspace_section(request, self.patient.id, 'reports_history')
        
        self.assertEqual(response.status_code, 200)
        # The view renders a template. We can check the context if we use the test client, 
        # but with factory/direct view call, we inspect the response content.
        # However, list.html uses active_tab variable in x-data.
        # "activeTab: 'images'" should be present in the content.
        
        self.assertContains(response, "activeTab: 'images'")

    def test_reports_partial_link_has_tab_param(self):
        """
        Test that the reports.html partial contains the link with ?tab=images.
        """
        # We need to mock the context required by reports.html
        # reports.html expects 'patient' and 'latest_reports'
        from django.template.loader import render_to_string
        
        context = {
            'patient': self.patient,
            'latest_reports': {'upload_date': '2023-01-01', 'images': []}
        }
        
        rendered = render_to_string('web_doctor/partials/home/reports.html', context)
        
        expected_url = reverse('web_doctor:patient_workspace_section', args=[self.patient.id, 'reports_history'])
        expected_link = f'hx-get="{expected_url}?tab=images"'
        
        self.assertIn(expected_link, rendered)
