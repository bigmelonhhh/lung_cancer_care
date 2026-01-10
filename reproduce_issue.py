
import os
import django
from django.conf import settings
from unittest.mock import MagicMock, patch
from datetime import datetime
from django.utils import timezone

# Configure Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lung_cancer_care.settings')
django.setup()

from web_patient.views.home import patient_home
from health_data.models import MetricType

def test_patient_home_logic():
    print("Starting reproduction test...")
    
    # Mock request
    request = MagicMock()
    request.user.id = 1
    request.user.is_authenticated = True
    request.user.is_active = True
    request.user.user_type = 1  # UserType.PATIENT
    request.GET = {}
    
    # Mock Patient
    patient = MagicMock()
    patient.id = 123
    patient.user_id = 1
    patient.name = "Test Patient"
    request.patient = patient
    
    # Mock Services
    with patch('web_patient.views.home.PatientService') as MockPatientService, \
         patch('web_patient.views.home.get_daily_plan_summary') as MockGetPlan, \
         patch('web_patient.views.home.HealthMetricService') as MockMetricService, \
         patch('web_patient.views.home.render') as MockRender:
         
        # Setup mocks
        MockPatientService.return_value.get_guard_days.return_value = ("10", "20")
        
        # Scenario: Backend says tasks are COMPLETED (status=1), but no metric data exists for today
        MockGetPlan.return_value = [
            {"title": "用药提醒", "task_type": 1, "status": 1}, # Medication completed
            {"title": "血氧监测", "task_type": 4, "status": 1}, # SpO2 completed (but no data)
            {"title": "血压监测", "task_type": 4, "status": 1}, # BP completed (but no data)
            {"title": "随访问卷", "task_type": 6, "status": 1}, # Followup completed
        ]
        
        # Return empty metric data (or old data)
        MockMetricService.query_last_metric.return_value = {} 
        
        # Call view
        patient_home(request)
        
        # Get context passed to render
        # render(request, template_name, context=None, ...)
        # Check positional args
        args, kwargs = MockRender.call_args
        if len(args) >= 3:
            context = args[2]
        else:
            context = kwargs.get('context', {})
            
        daily_plans = context.get('daily_plans', [])
        
        print("\n--- Analysis Results ---")
        for plan in daily_plans:
            print(f"Plan: {plan['title']}")
            print(f"  Type: {plan['type']}")
            print(f"  Status: {plan['status']}")
            print(f"  Subtitle: {plan['subtitle']}")
            print(f"  Action Text: {plan['action_text']}")
            
            # Check for the issue
            if plan['status'] == 'completed' and '请记录' in plan['subtitle']:
                print("  [ISSUE DETECTED] Status is completed (button hidden) but subtitle asks to record.")
            elif plan['status'] == 'completed':
                 print("  [OK] Status is completed.")
            else:
                 print("  [OK] Status is pending.")
            print("-" * 30)

if __name__ == "__main__":
    test_patient_home_logic()
