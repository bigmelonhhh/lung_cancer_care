import os
import django
from django.test import RequestFactory
from django.contrib.auth import get_user_model

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "lung_cancer_care.settings")
django.setup()

from web_patient.views import patient_dashboard
from users.models import PatientProfile
from users import choices

User = get_user_model()

def verify():
    print("Starting verification...")
    
    # 1. Create Mock User & Patient
    user, _ = User.objects.get_or_create(
        username="test_patient_dash", 
        defaults={
            "user_type": choices.UserType.PATIENT,
            "wx_openid": "mock_openid_dash"
        }
    )
    patient, _ = PatientProfile.objects.get_or_create(
        user=user, 
        defaults={
            "name": "Test Patient Dash",
            "phone": "13800009999"  # Provide unique phone to avoid IntegrityError
        }
    )
    
    # 2. Mock Request
    factory = RequestFactory()
    request = factory.get('/p/dashboard/')
    request.user = user
    request.patient = patient
    
    # 3. Call View
    response = patient_dashboard(request)
    print(f"Dashboard status: {response.status_code}")
    
    # 4. Inspect Context (requires looking into the response content or context if using TemplateResponse)
    # Since it returns HttpResponse(render(...)), we can check the rendered content for the URL.
    # The expected URL is /p/health/records/
    
    content = response.content.decode()
    expected_url = "/p/health/records/"
    
    if expected_url in content:
        print(f"SUCCESS: Found link to {expected_url}")
    else:
        print(f"FAIL: Could not find link to {expected_url}")
        # print snippet
        # print(content[:1000])

if __name__ == "__main__":
    verify()
