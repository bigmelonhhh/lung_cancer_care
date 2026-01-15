from users.models import PatientProfile
from chat.models import PatientStudioAssignment
from django.utils import timezone

def run():
    patients = PatientProfile.objects.all()
    count = 0
    for patient in patients:
        doctor = patient.doctor
        if not doctor or not getattr(doctor, "studio", None):
            continue

        # Check if active assignment exists
        active = PatientStudioAssignment.objects.filter(patient=patient, end_at__isnull=True).first()
        if not active:
            PatientStudioAssignment.objects.create(
                patient=patient,
                studio=doctor.studio,
                start_at=timezone.now(),
                reason="Auto-assigned by script"
            )
            print(f"Assigned {patient.name} to {doctor.studio.name}")
            count += 1
    print(f"Total assigned: {count}")
