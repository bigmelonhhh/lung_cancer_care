from django.test import TestCase, RequestFactory
from django.urls import reverse
from users.models import CustomUser, PatientProfile
from users import choices
from web_patient.views import patient_dashboard

class DashboardMedicationLinkTest(TestCase):
    def setUp(self):
        # Create a user and patient
        self.user = CustomUser.objects.create_user(
            username="test_med_dash",
            user_type=choices.UserType.PATIENT,
            wx_openid="mock_openid_med_dash"
        )
        self.patient = PatientProfile.objects.create(
            user=self.user,
            name="Test Patient Med Dash",
            phone="13800008888"
        )
        self.factory = RequestFactory()

    def test_dashboard_medication_link(self):
        # Create a request
        request = self.factory.get(reverse('web_patient:patient_dashboard'))
        request.user = self.user
        request.patient = self.patient

        # Call the view
        response = patient_dashboard(request)
        
        # Check status code
        self.assertEqual(response.status_code, 200)
        
        # Check content for the link
        content = response.content.decode()
        expected_url = reverse("web_patient:my_medication")
        
        # We look for the URL in the rendered HTML
        # Since it's a bit hard to parse HTML with regex perfectly, 
        # we just check if the URL string is present in the response content.
        # Ideally, we should check if it's associated with "我的用药", 
        # but presence is a strong enough signal for this unit test given the simple change.
        self.assertIn(expected_url, content)
        self.assertIn("我的用药", content)
