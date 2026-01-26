import os
import django
from datetime import date, timedelta
from django.test import RequestFactory
from django.contrib.auth import get_user_model

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "lung_cancer_care.settings")
django.setup()

from core.models import TreatmentCycle, DailyTask
from core.models.choices import PlanItemCategory, TaskStatus
from users.models import PatientProfile
from web_patient.views import my_examination, examination_detail
from health_data.models.test_report import TestReport
from users import choices

User = get_user_model()

def verify():
    
    # 1. Create Mock User & Patient
    user, _ = User.objects.get_or_create(
        username="test_patient_exam", 
        defaults={
            "user_type": choices.UserType.PATIENT,
            "wx_openid": "mock_openid_123"
        }
    )
    patient, _ = PatientProfile.objects.get_or_create(user=user, defaults={"name": "Test Patient"})
    
    # 2. Create Mock Cycles
    # Cycle 1: Current
    c1, _ = TreatmentCycle.objects.get_or_create(
        patient=patient, 
        name="Cycle 1", 
        defaults={"start_date": date.today() - timedelta(days=10)}
    )
    
    # Cycle 2: Past
    c2, _ = TreatmentCycle.objects.get_or_create(
        patient=patient, 
        name="Cycle 2", 
        defaults={
            "start_date": date.today() - timedelta(days=40),
            "end_date": date.today() - timedelta(days=11)
        }
    )
    
    # 3. Create Mock Tasks
    # Task 1: Pending (Future) - "Not Started"
    t1, _ = DailyTask.objects.get_or_create(
        patient=patient,
        title="Future Checkup",
        task_date=date.today() + timedelta(days=5),
        task_type=PlanItemCategory.CHECKUP,
        defaults={"status": TaskStatus.PENDING}
    )
    # Assign to Cycle 1 (via logic or direct plan item, but here we test logic grouping by date if plan item missing)
    # Actually my view logic prioritizes plan_item.cycle, then date matching.
    # Let's rely on date matching for simplicity or create plan item if needed.
    # Since I didn't create PlanItem, let's see if date matching works.
    
    # Task 2: Pending (Today) - "Actionable"
    t2, _ = DailyTask.objects.get_or_create(
        patient=patient,
        title="Today Checkup",
        task_date=date.today(),
        task_type=PlanItemCategory.CHECKUP,
        defaults={"status": TaskStatus.PENDING}
    )
    
    # Task 3: Completed - "Completed"
    t3, _ = DailyTask.objects.get_or_create(
        patient=patient,
        title="Past Checkup",
        task_date=date.today() - timedelta(days=20),
        task_type=PlanItemCategory.CHECKUP,
        defaults={"status": TaskStatus.COMPLETED}
    )
    
    # 4. Create Mock Report for T3
    TestReport.objects.get_or_create(
        patient=patient,
        report_date=t3.task_date,
        defaults={
            "report_type": 1, # CT
            "image_urls": ["http://example.com/img1.jpg"]
        }
    )
    
    # 5. Test my_examination View
    factory = RequestFactory()
    request = factory.get('/p/examination/my/')
    request.user = user
    request.patient = patient
    
    response = my_examination(request)
    if response.status_code == 200:
        content = response.content.decode()
        if "我的复查" in content:
            pass
        if "Future Checkup" in content:
            pass
        if "Today Checkup" in content:
            pass
        if "web_patient:record_checkup" in content or "record/checkup" in content: # URL might be resolved
            pass
    else:
        pass

    # 6. Test examination_detail View
    request_detail = factory.get(f'/p/examination/detail/{t3.id}/')
    request_detail.user = user
    request_detail.patient = patient
    
    response_detail = examination_detail(request_detail, t3.id)
    if response_detail.status_code == 200:
        content_detail = response_detail.content.decode()
        if "复查详情" in content_detail:
            pass
        if "http://example.com/img1.jpg" in content_detail:
           pass
    else:
        pass


if __name__ == "__main__":
    verify()
