import os
import django
from datetime import date, timedelta
from django.utils import timezone

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "lung_cancer_care.settings")
django.setup()

from users.models import PatientProfile, CustomUser
from core.models import TreatmentCycle, Questionnaire
from health_data.models import QuestionnaireSubmission
from health_data.services.questionnaire_submission import QuestionnaireSubmissionService
from core.service.treatment_cycle import create_treatment_cycle

def reproduce():
    # 1. Setup Data
    print("Setting up data...")
    user, _ = CustomUser.objects.get_or_create(username="test_patient_history", user_type=1)
    patient, _ = PatientProfile.objects.get_or_create(user=user, name="Test History Patient", birth_date=date(1990, 1, 1))
    
    # Clean up previous runs
    TreatmentCycle.objects.filter(patient=patient).delete()
    QuestionnaireSubmission.objects.filter(patient_id=patient.id).delete()
    
    # Create Cycle 1: Jan 1 - Jan 10
    cycle1 = TreatmentCycle.objects.create(
        patient=patient,
        name="Cycle 1",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 10),
        status=2 # COMPLETED
    )
    
    # Create Cycle 2: Feb 1 - Feb 10
    cycle2 = TreatmentCycle.objects.create(
        patient=patient,
        name="Cycle 2",
        start_date=date(2025, 2, 1),
        end_date=date(2025, 2, 10),
        status=1 # IN_PROGRESS
    )
    
    # Ensure a questionnaire exists
    q, _ = Questionnaire.objects.get_or_create(code="Q_TEST", name="Test Q")
    
    # Create Submission in Cycle 1 (Jan 5)
    s1 = QuestionnaireSubmission.objects.create(
        patient_id=patient.id,
        questionnaire=q,
    )
    s1.created_at = timezone.make_aware(datetime(2025, 1, 5, 10, 0, 0))
    s1.save()
    
    # Create Submission in Cycle 2 (Feb 5)
    s2 = QuestionnaireSubmission.objects.create(
        patient_id=patient.id,
        questionnaire=q,
    )
    s2.created_at = timezone.make_aware(datetime(2025, 2, 5, 10, 0, 0))
    s2.save()
    
    print(f"Total Submissions: {QuestionnaireSubmission.objects.filter(patient_id=patient.id).count()}")
    for s in QuestionnaireSubmission.objects.filter(patient_id=patient.id):
        print(f"Submission: {s.created_at}")
    
    # 2. Run Logic
    print("Running view logic...")
    cycles = [cycle2, cycle1] # reverse order usually
    
    history = []
    for cycle in cycles:
        print(f"Processing {cycle.name}: {cycle.start_date} - {cycle.end_date}")
        dates = QuestionnaireSubmissionService.get_submission_dates(
            patient=patient,
            start_date=cycle.start_date,
            end_date=cycle.end_date
        )
        print(f"  Dates found: {dates}")
        history.append({
            "name": cycle.name,
            "dates": dates
        })
        
    # 3. Check Results
    cycle1_dates = next(item['dates'] for item in history if item['name'] == "Cycle 1")
    cycle2_dates = next(item['dates'] for item in history if item['name'] == "Cycle 2")
    
    print("\nResults:")
    print(f"Cycle 1 Dates: {cycle1_dates}")
    print(f"Cycle 2 Dates: {cycle2_dates}")
    
    if len(cycle1_dates) == 1 and cycle1_dates[0] == date(2025, 1, 5) and \
       len(cycle2_dates) == 1 and cycle2_dates[0] == date(2025, 2, 5):
        print("SUCCESS: Dates are correctly separated.")
    else:
        print("FAILURE: Dates are mixed or incorrect.")

from datetime import datetime
if __name__ == "__main__":
    try:
        reproduce()
    except Exception as e:
        import traceback
        traceback.print_exc()
