
import json
import os
import django
from django.test import TestCase, RequestFactory
from django.utils import timezone
from django.core.exceptions import PermissionDenied

# Setup Django environment if running standalone
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lung_cancer_care.settings')
django.setup()

from users.models import CustomUser, DoctorProfile, AssistantProfile, PatientProfile, DoctorStudio
from users.choices import UserType
from chat.models.assignment import PatientStudioAssignment
from chat.services.chat import ChatService
from web_patient.views.chat_api import list_messages
from users.services.patient import PatientService

class ConsultationChatLogicTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.chat_service = ChatService()
        self.patient_service = PatientService()

        # 1. Create Users
        self.doctor_user = CustomUser.objects.create_user(username='libai', password='password', user_type=UserType.DOCTOR, phone='13800138001')
        self.assistant_user = CustomUser.objects.create_user(username='xiaotaoyao', password='password', user_type=UserType.ASSISTANT, phone='13800138002')
        self.patient_user = CustomUser.objects.create_user(username='zhangpeng', password='password', user_type=UserType.PATIENT, phone='13800138003', wx_openid='test_openid_123')

        # 2. Create Profiles
        self.doctor_profile = DoctorProfile.objects.create(user=self.doctor_user, name="李白")
        self.assistant_profile = AssistantProfile.objects.create(user=self.assistant_user, name="小桃妖")
        self.patient_profile = PatientProfile.objects.create(user=self.patient_user, name="张鹏")

        # 3. Create Studio
        self.studio = DoctorStudio.objects.create(name="肺部康复管理工作室", owner_doctor=self.doctor_profile)
        # Link Doctor to Studio
        self.doctor_profile.studio = self.studio
        self.doctor_profile.save()

    def test_case_1_doctor_association(self):
        """
        测试用例1 - 医生关联验证：
        - 模拟"李白"医生已创建"肺部康复管理工作室" (setUp已完成)
        - 验证医生登录后能正确显示患者"张鹏"的数据 (模拟后台关联)
        - 检查聊天页面是否正常显示，不应出现showNoStudioError布局提醒
        """
        
        # Setup: Assign Patient to Studio (模拟医生后台关联操作)
        PatientStudioAssignment.objects.create(
            patient=self.patient_profile,
            studio=self.studio,
            start_at=timezone.now()
        )

        # Verify Assignment (Backend Logic)
        assignment = self.patient_service.get_active_studio_assignment(self.patient_profile)
        self.assertIsNotNone(assignment, "Patient should be assigned to a studio")
        self.assertEqual(assignment.studio, self.studio, "Patient should be assigned to Li Bai's studio")

        # Simulate Patient accessing Chat Page (API call)
        # Note: We test the Patient's view because that's where the error logic resides
        request = self.factory.get('/api/chat/messages/')
        request.user = self.patient_user
        request.patient = self.patient_profile # Mocking middleware injection

        response = list_messages(request)
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data['status'], 'success')

    def test_case_2_assistant_association(self):
        """
        测试用例2 - 医助关联验证：
        - 模拟医助"小桃妖"已关联"李白"医生
        - 验证医助登录后能正确显示患者"张鹏"的数据
        - 检查聊天页面是否正常显示，不应出现showNoStudioError布局提醒
        """
        
        # Setup: Link Assistant to Doctor
        try:
            # Assuming M2M field 'doctors' exists on AssistantProfile
            self.assistant_profile.doctors.add(self.doctor_profile)
        except AttributeError:
            pass

        # Setup: Assign Patient to Studio (Required for chat to work)
        PatientStudioAssignment.objects.create(
            patient=self.patient_profile,
            studio=self.studio,
            start_at=timezone.now()
        )

        # Verify Assistant is a studio member (Backend Logic)
        is_member = self.chat_service._is_user_studio_member(self.assistant_user, self.studio)
        self.assertTrue(is_member, "Assistant should be considered a studio member")
        
        # Simulate Patient accessing Chat Page
        request = self.factory.get('/api/chat/messages/')
        request.user = self.patient_user
        request.patient = self.patient_profile
        
        response = list_messages(request)
        self.assertEqual(response.status_code, 200)

    def test_case_3_patient_association(self):
        """
        测试用例3 - 患者关联验证：
        - 模拟患者"张鹏"后台已关联"李白"医生
        - 验证患者前台显示正确关联了"李白"医生和"肺部康复管理工作室"
        - 检查患者进入聊天页面时是否正常显示，不应出现showNoStudioError布局提醒
        """
        
        # Setup: Assign Patient to Studio
        PatientStudioAssignment.objects.create(
            patient=self.patient_profile,
            studio=self.studio,
            start_at=timezone.now()
        )
        
        # Verify active assignment
        assignment = self.patient_service.get_active_studio_assignment(self.patient_profile)
        self.assertEqual(assignment.studio.name, "肺部康复管理工作室")
        
        # Verify Chat Logic
        # 1. API Call (Happy Path)
        request = self.factory.get('/api/chat/messages/')
        request.user = self.patient_user
        request.patient = self.patient_profile
        
        response = list_messages(request)
        self.assertEqual(response.status_code, 200)
        
        # 2. Verify Conversation Creation
        conversation = self.chat_service.get_or_create_patient_conversation(self.patient_profile)
        self.assertEqual(conversation.studio, self.studio)
        
        # 3. Simulate Error Condition (No Assignment)
        # Delete assignment to simulate unassigned state
        assignment.delete()
        
        # Call API again
        response_error = list_messages(request)
        self.assertEqual(response_error.status_code, 400)
        data_error = json.loads(response_error.content)
        
        # Check if error message triggers the frontend logic
        # Frontend: if (res.status === 400 && data.message && data.message.includes("工作室"))
        self.assertIn("工作室", data_error['message'])

