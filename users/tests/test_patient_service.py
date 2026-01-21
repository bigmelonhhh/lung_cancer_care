import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from users import choices
from chat.models import PatientStudioAssignment
from users.models import (
    AssistantProfile,
    CustomUser,
    DoctorProfile,
    DoctorStudio,
    PatientProfile,
    PatientRelation,
    SalesProfile,
)
from users.services.patient import PatientService


class PatientServiceTests(TestCase):
    def setUp(self):
        """Set up test data for the test cases."""
        self.service = PatientService()

        # 1. Create a Doctor
        self.doctor_user = CustomUser.objects.create_user(
            user_type=choices.UserType.DOCTOR,
            phone="13800138000",
            wx_nickname="Dr. House",
        )
        self.doctor_profile = DoctorProfile.objects.create(
            user=self.doctor_user, name="Dr. House", hospital="Test Hospital"
        )
        self.studio = DoctorStudio.objects.create(
            name="Doctor Studio",
            code="STU100",
            owner_doctor=self.doctor_profile,
        )
        self.doctor_profile.studio = self.studio
        self.doctor_profile.save(update_fields=["studio"])

        # 2. Create an Assistant linked to the doctor
        self.assistant_user = CustomUser.objects.create_user(
            user_type=choices.UserType.ASSISTANT,
            phone="13700137000",
            wx_nickname="Assistant Amy",
        )
        self.assistant_profile = AssistantProfile.objects.create(
            user=self.assistant_user,
            name="Assistant Amy",
        )
        self.assistant_profile.doctors.add(self.doctor_profile)

        # 3. Create a Patient, and assign the doctor
        self.patient_user = CustomUser.objects.create_user(
            user_type=choices.UserType.PATIENT,
            wx_openid="patient_openid_12345",
            wx_nickname="John Doe",
        )
        self.patient_profile = PatientProfile.objects.create(
            user=self.patient_user,
            phone="18600000001",
            name="John Doe",
            doctor=self.doctor_profile,
            birth_date=datetime.date(1980, 5, 15),
        )

        # 4. Create a Family Member for the patient
        self.family_user = CustomUser.objects.create_user(
            user_type=choices.UserType.PATIENT,  # Family members are also 'PATIENT' type
            wx_openid="family_openid_67890",
            wx_nickname="Jane Doe",
        )
        self.patient_relation = PatientRelation.objects.create(
            patient=self.patient_profile,
            user=self.family_user,
            relation_type=choices.RelationType.SPOUSE,
            name="Jane Doe",
            is_active=True,
        )

        # 5. Create a Sales user
        self.unauthorized_user = CustomUser.objects.create_user(
            user_type=choices.UserType.SALES,
            phone="13900139000",
            wx_nickname="Sales Sam",
        )
        self.sales_profile = SalesProfile.objects.create(
            user=self.unauthorized_user,
            name="Sales Sam",
        )
        self.sales_profile.doctors.add(self.doctor_profile)

        # 6. Create an unclaimed profile for claim tests
        self.unclaimed_profile = PatientProfile.objects.create(
            phone="18600000002",
            name="Unclaimed Patient",
            doctor=None,
        )
        
        # 7. Another patient for phone conflict test
        self.other_patient_user = CustomUser.objects.create_user(
            user_type=choices.UserType.PATIENT,
            wx_openid="other_patient_openid_abcde",
        )
        self.other_patient_profile = PatientProfile.objects.create(
            user=self.other_patient_user,
            phone="18600000003",
            name="Other Patient"
        )

        self.unassigned_patient = PatientProfile.objects.create(
            phone="18600000004",
            name="Unassigned Patient",
        )


    def test_edit_by_self_success(self):
        """A patient can successfully edit their own profile."""
        update_data = {
            "name": "John Doe Updated",
            "phone": "18600000001", # Phone unchanged
            "gender": choices.Gender.MALE,
            "birth_date": datetime.date(1981, 6, 16),
            "address": "123 New Address St",
            "remark": "需重点关注随访",
        }
        
        updated_profile = self.service.save_patient_profile(
            user=self.patient_user,
            data=update_data,
            profile_id=self.patient_profile.id,
        )

        self.patient_profile.refresh_from_db()
        self.assertEqual(updated_profile.id, self.patient_profile.id)
        self.assertEqual(self.patient_profile.name, "John Doe Updated")
        self.assertEqual(self.patient_profile.address, "123 New Address St")
        self.assertEqual(self.patient_profile.birth_date, datetime.date(1981, 6, 16))
        self.assertEqual(self.patient_profile.remark, "需重点关注随访")

    def test_edit_by_doctor_success(self):
        """The assigned doctor can successfully edit a patient's profile."""
        update_data = {
            "name": "John Doe (Edited by Doctor)",
            "phone": "18600000001",
            "remark": "医生备注更新",
        }
        
        updated_profile = self.service.save_patient_profile(
            user=self.doctor_user,
            data=update_data,
            profile_id=self.patient_profile.id,
        )
        
        self.patient_profile.refresh_from_db()
        self.assertEqual(self.patient_profile.name, "John Doe (Edited by Doctor)")
        self.assertEqual(self.patient_profile.remark, "医生备注更新")

    def test_edit_by_family_member_success(self):
        """An active family member can successfully edit the patient's profile."""
        update_data = {"name": "John Doe (Edited by Family)", "phone": "18600000001"}

        updated_profile = self.service.save_patient_profile(
            user=self.family_user,
            data=update_data,
            profile_id=self.patient_profile.id,
        )

        self.patient_profile.refresh_from_db()
        self.assertEqual(self.patient_profile.name, "John Doe (Edited by Family)")
        
    def test_edit_by_assistant_success(self):
        """A doctor's assistant can successfully edit a patient's remark."""
        update_data = {
            "name": "John Doe",
            "phone": "18600000001",
            "remark": "助理备注更新",
        }

        updated_profile = self.service.save_patient_profile(
            user=self.assistant_user,
            data=update_data,
            profile_id=self.patient_profile.id,
        )

        self.patient_profile.refresh_from_db()
        self.assertEqual(updated_profile.id, self.patient_profile.id)
        self.assertEqual(self.patient_profile.remark, "助理备注更新")

    def test_edit_non_existent_profile_fails(self):
        """Editing a profile with a non-existent ID fails."""
        update_data = {"name": "Test", "phone": "12345"}
        
        with self.assertRaisesRegex(ValidationError, "档案不存在"):
            self.service.save_patient_profile(
                user=self.doctor_user, data=update_data, profile_id=99999
            )

    def test_edit_phone_conflict_fails(self):
        """Editing a profile to use a phone number already taken by another profile fails."""
        update_data = {
            "name": "John Doe",
            "phone": self.other_patient_profile.phone,  # Use other patient's phone
        }
        
        with self.assertRaisesRegex(ValidationError, "该手机号已被其他档案占用"):
            self.service.save_patient_profile(
                user=self.patient_user,
                data=update_data,
                profile_id=self.patient_profile.id,
            )

    def test_claim_existing_unclaimed_profile_success(self):
        """A new user can claim an existing, unclaimed profile using the correct phone number."""
        new_user = CustomUser.objects.create_user(
            user_type=choices.UserType.PATIENT,
            wx_openid="new_user_openid_xyz",
            wx_nickname="New Claimant",
        )
        claim_data = {
            "name": "Unclaimed Patient Updated",
            "phone": self.unclaimed_profile.phone,
        }
        
        # Call without profile_id to trigger claim/create logic
        claimed_profile = self.service.save_patient_profile(user=new_user, data=claim_data)
        
        self.unclaimed_profile.refresh_from_db()
        self.assertEqual(claimed_profile.id, self.unclaimed_profile.id)
        self.assertEqual(self.unclaimed_profile.user, new_user)
        self.assertEqual(self.unclaimed_profile.name, "Unclaimed Patient Updated")
        self.assertEqual(self.unclaimed_profile.claim_status, choices.ClaimStatus.CLAIMED)
        
    def test_create_new_profile_success(self):
        """A user can create a brand new profile with a new phone number."""
        new_user = CustomUser.objects.create_user(
            user_type=choices.UserType.PATIENT,
            wx_openid="creator_openid_abc",
            wx_nickname="Profile Creator",
        )
        create_data = {
            "name": "Brand New Patient",
            "phone": "18600009999", # New phone
            "gender": choices.Gender.FEMALE,
            "remark": "首次建档备注",
        }

        # Call without profile_id to trigger claim/create logic
        new_profile = self.service.save_patient_profile(user=new_user, data=create_data)
        
        self.assertIsNotNone(new_profile.id)
        self.assertEqual(new_profile.user, new_user)
        self.assertEqual(new_profile.name, "Brand New Patient")
        self.assertEqual(new_profile.phone, "18600009999")
        self.assertEqual(new_profile.source, choices.PatientSource.SELF)
        self.assertEqual(new_profile.remark, "首次建档备注")

    def test_assign_doctor_creates_studio_assignment(self):
        """绑定医生时应创建患者工作室归属记录。"""
        self.service.assign_doctor(
            patient=self.unassigned_patient,
            doctor_id=self.doctor_profile.id,
            sales_user=self.unauthorized_user,
        )
        assignment = PatientStudioAssignment.objects.filter(
            patient=self.unassigned_patient, end_at__isnull=True
        ).first()
        self.assertIsNotNone(assignment)
        self.assertEqual(assignment.studio_id, self.studio.id)

    def test_claim_profile_already_bound_fails(self):
        """Attempting to claim a profile already bound to another user fails."""
        attacker_user = CustomUser.objects.create_user(
            user_type=choices.UserType.PATIENT,
            wx_openid="attacker_openid_qwerty",
        )
        claim_data = {
            "name": "Attempted Takeover",
            "phone": self.patient_profile.phone,  # Phone of a bound profile
        }
        
        with self.assertRaisesRegex(ValidationError, "该手机号已被其他微信账号绑定，请联系顾问处理。"):
            self.service.save_patient_profile(user=attacker_user, data=claim_data)

    def test_missing_name_or_phone_fails(self):
        """Calling the service without a name or phone in the data fails."""
        with self.assertRaisesRegex(ValidationError, "姓名与手机号必填"):
            self.service.save_patient_profile(
                user=self.patient_user, data={"name": "Only Name"}
            )
            
        with self.assertRaisesRegex(ValidationError, "姓名与手机号必填"):
            self.service.save_patient_profile(
                user=self.patient_user, data={"phone": "1234567890"}
            )

    def test_remark_too_long_fails(self):
        """Remark longer than 500 chars should raise ValidationError."""
        update_data = {
            "name": "John Doe Updated",
            "phone": "18600000001",
            "remark": "a" * 501,
        }

        with self.assertRaisesRegex(ValidationError, "备注不能超过500字"):
            self.service.save_patient_profile(
                user=self.patient_user,
                data=update_data,
                profile_id=self.patient_profile.id,
            )

    def test_edit_baseline_fields_success(self):
        """Editing a profile updates baseline monitoring fields."""
        update_data = {
            "name": "John Doe",
            "phone": "18600000001",
            "baseline_body_temperature": Decimal("36.6"),
            "baseline_blood_oxygen": 98,
            "baseline_weight": Decimal("68.5"),
            "baseline_blood_pressure_sbp": 120,
            "baseline_blood_pressure_dbp": 80,
            "baseline_heart_rate": 72,
            "baseline_steps": 6000,
        }

        updated_profile = self.service.save_patient_profile(
            user=self.doctor_user,
            data=update_data,
            profile_id=self.patient_profile.id,
        )

        self.patient_profile.refresh_from_db()
        self.assertEqual(updated_profile.id, self.patient_profile.id)
        self.assertEqual(self.patient_profile.baseline_body_temperature, Decimal("36.6"))
        self.assertEqual(self.patient_profile.baseline_blood_oxygen, 98)
        self.assertEqual(self.patient_profile.baseline_weight, Decimal("68.5"))
        self.assertEqual(self.patient_profile.baseline_blood_pressure_sbp, 120)
        self.assertEqual(self.patient_profile.baseline_blood_pressure_dbp, 80)
        self.assertEqual(self.patient_profile.baseline_heart_rate, 72)
        self.assertEqual(self.patient_profile.baseline_steps, 6000)
