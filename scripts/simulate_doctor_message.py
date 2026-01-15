from users.models import PatientProfile, DoctorProfile, DoctorStudio, CustomUser
from chat.services.chat import ChatService
from users.choices import UserType

def run():
    # Find a patient
    patient = PatientProfile.objects.first()
    if not patient:
        return

    # Find conversation
    service = ChatService()
    try:
        conversation = service.get_or_create_patient_conversation(patient)
        studio = conversation.studio
        if not studio:
            return
            
        # Create a Platform Doctor (if not exists)
        # Check if there is a doctor in this studio who is NOT the owner
        pf_doctor = DoctorProfile.objects.filter(studio=studio).exclude(id=studio.owner_doctor_id).first()
        
        if not pf_doctor:
            # Create user
            username = 'pf_doctor_test'
            user = CustomUser.objects.filter(username=username).first()
            if not user:
                user = CustomUser.objects.create_user(username=username, password='password', user_type=UserType.DOCTOR, phone='13900000000')
            
            pf_doctor = DoctorProfile.objects.create(user=user, name='Dr Platform', studio=studio)
        
        
        # Send Text Message
        msg = service.create_text_message(
            conversation=conversation,
            sender=pf_doctor.user,
            content="你好，这是医生发送的测试消息。\n第二行测试换行。\n😊表情测试。"
        )
        
    except Exception as e:
        pass
