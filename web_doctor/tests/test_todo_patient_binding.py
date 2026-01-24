
from django.test import TestCase, Client
from django.urls import reverse
from users.models import CustomUser, DoctorProfile, PatientProfile
from users.choices import UserType
from patient_alerts.models import PatientAlert, AlertEventType, AlertLevel, AlertStatus
from patient_alerts.services.todo_list import TodoListService

class TodoPatientBindingTests(TestCase):
    def setUp(self):
        # Create Doctor User
        self.doctor_user = CustomUser.objects.create_user(
            username='doctor', 
            password='password123', 
            user_type=UserType.DOCTOR,
            phone='13800000000'
        )
        self.doctor_profile = DoctorProfile.objects.create(
            user=self.doctor_user, name='Dr. Test'
        )
        
        # Create Patients
        # Note: create_user handles password hashing
        self.patient1 = PatientProfile.objects.create(
            user=CustomUser.objects.create_user(
                username='p1', 
                user_type=UserType.PATIENT,
                phone='13800000001',
                wx_openid='openid_p1'
            ),
            doctor=self.doctor_profile,
            name='Patient One',
            phone='13800000001'
        )
        self.patient2 = PatientProfile.objects.create(
            user=CustomUser.objects.create_user(
                username='p2', 
                user_type=UserType.PATIENT,
                phone='13800000002',
                wx_openid='openid_p2'
            ),
            doctor=self.doctor_profile,
            name='Patient Two',
            phone='13800000002'
        )
        
        # Create Alerts (Todos)
        # Patient 1 has 2 pending alerts
        PatientAlert.objects.create(
            patient=self.patient1,
            doctor=self.doctor_profile,
            event_type=AlertEventType.DATA,
            event_level=AlertLevel.MILD,
            event_title='P1 Alert 1',
            status=AlertStatus.PENDING
        )
        PatientAlert.objects.create(
            patient=self.patient1,
            doctor=self.doctor_profile,
            event_type=AlertEventType.BEHAVIOR,
            event_level=AlertLevel.MODERATE,
            event_title='P1 Alert 2',
            status=AlertStatus.PENDING
        )
        
        # Patient 2 has 1 pending alert
        PatientAlert.objects.create(
            patient=self.patient2,
            doctor=self.doctor_profile,
            event_type=AlertEventType.DATA,
            event_level=AlertLevel.MILD,
            event_title='P2 Alert 1',
            status=AlertStatus.PENDING
        )
        
        self.client = Client()
        self.client.login(username='doctor', password='password123')

    def test_service_filters_by_patient_id(self):
        """Test TodoListService.get_todo_page with patient_id filter"""
        # Test for Patient 1
        page_p1 = TodoListService.get_todo_page(
            user=self.doctor_user,
            patient_id=self.patient1.id,
            status='pending'
        )
        self.assertEqual(len(page_p1.object_list), 2)
        self.assertTrue(all(item['patient_name'] == 'Patient One' for item in page_p1.object_list))
        
        # Test for Patient 2
        page_p2 = TodoListService.get_todo_page(
            user=self.doctor_user,
            patient_id=self.patient2.id,
            status='pending'
        )
        self.assertEqual(len(page_p2.object_list), 1)
        self.assertEqual(page_p2.object_list[0]['patient_name'], 'Patient Two')
        
        # Test without patient_id (should return all for doctor)
        page_all = TodoListService.get_todo_page(
            user=self.doctor_user,
            status='pending'
        )
        self.assertEqual(len(page_all.object_list), 3)

    def test_patient_workspace_view_oob_sidebar(self):
        """Test patient_workspace view returns OOB sidebar update"""
        url = reverse('web_doctor:patient_workspace', args=[self.patient1.id])
        response = self.client.get(url, headers={'HX-Request': 'true'})
        
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        
        # Check if main content is rendered (settings tab)
        self.assertIn('管理设置', content)
        
        # Check if OOB sidebar is present
        self.assertIn('hx-swap-oob="true"', content)
        self.assertIn('id="patient-todo-list"', content)
        
        # Check if Patient 1's todos are present in the sidebar
        self.assertIn('Patient One的待办', content)
        self.assertIn('P1 Alert 1', content)
        self.assertIn('P1 Alert 2', content)
        self.assertNotIn('P2 Alert 1', content)

    def test_todo_list_page_filters_by_patient_id(self):
        """Test doctor_todo_list_page view with patient_id param"""
        url = reverse('web_doctor:doctor_todo_list')
        
        # Filter by Patient 1
        response = self.client.get(url, {'patient_id': self.patient1.id, 'status': 'pending'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'P1 Alert 1')
        self.assertContains(response, 'P1 Alert 2')
        self.assertNotContains(response, 'P2 Alert 1')
        
        # Verify pagination links preserve patient_id
        # Note: Pagination might not show if items < page size (10), but we can check context
        self.assertEqual(str(response.context['patient_id']), str(self.patient1.id))
        
        # Check if hidden input exists in form (if we rendered the full page)
        self.assertContains(response, f'name="patient_id" value="{self.patient1.id}"')

    def test_todo_list_page_htmx_table_only(self):
        """Test doctor_todo_list_page with HTMX request returns table only"""
        url = reverse('web_doctor:doctor_todo_list')
        response = self.client.get(
            url, 
            {'patient_id': self.patient1.id, 'status': 'pending'},
            headers={'HX-Request': 'true'}
        )
        
        self.assertEqual(response.status_code, 200)
        # Should not contain full page layout
        self.assertNotContains(response, '<html')
        self.assertNotContains(response, '<body')
        
        # Should contain table rows
        self.assertContains(response, 'P1 Alert 1')
        
        # Should contain pagination links with patient_id
        # Since we have only 2 items and default size is 10, no pagination links rendered.
        # But we can force small page size to test pagination
        
        response_paged = self.client.get(
            url,
            {'patient_id': self.patient1.id, 'status': 'pending', 'size': 1},
            headers={'HX-Request': 'true'}
        )
        self.assertContains(response_paged, f'patient_id={self.patient1.id}')

    def test_patient_todo_sidebar_view(self):
        """Test the new patient_todo_sidebar view for partial refresh"""
        url = reverse('web_doctor:patient_todo_sidebar', args=[self.patient1.id])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        
        # Check OOB attributes
        self.assertIn('hx-swap-oob="true"', content)
        self.assertIn('id="patient-todo-list"', content)
        
        # Check data
        self.assertIn('Patient One的待办', content)
        self.assertIn('P1 Alert 1', content)
        
        # Check data-patient-id attribute (Task 3 verification)
        self.assertIn(f'data-patient-id="{self.patient1.id}"', content)

    def test_todo_list_table_buttons_include_data_patient_id(self):
        url = reverse('web_doctor:doctor_todo_list')
        response = self.client.get(
            url,
            {'patient_id': self.patient1.id, 'status': 'pending'},
            headers={'HX-Request': 'true'}
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn(f'data-patient-id="{self.patient1.id}"', content)

    def test_doctor_workspace_contains_pending_jump_script_hook(self):
        url = reverse('web_doctor:doctor_workspace')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('todo_pending_jump', content)
