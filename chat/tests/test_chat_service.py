import base64
from datetime import date, datetime, timedelta
from unittest import mock

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from chat.models import (
    ConversationSession,
    ConversationType,
    MessageContentType,
    PatientStudioAssignment,
)
from chat.services import ChatService
from users import choices
from users.models import (
    AssistantProfile,
    CustomUser,
    DoctorProfile,
    DoctorStudio,
    PatientProfile,
    PatientRelation,
    SalesProfile,
)


PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVQImWNgYGBgAAAABQABDQottAAAAABJRU5ErkJggg=="
)


def build_test_image(filename="test.png"):
    """Create a small valid PNG for ImageField tests."""

    return SimpleUploadedFile(
        filename,
        base64.b64decode(PNG_BASE64),
        content_type="image/png",
    )


class ChatServiceTests(TestCase):
    def setUp(self):
        self.service = ChatService()

        self.director_user = CustomUser.objects.create_user(
            user_type=choices.UserType.DOCTOR,
            phone="13800138000",
            wx_nickname="Director",
        )
        self.director_profile = DoctorProfile.objects.create(
            user=self.director_user,
            name="Director A",
            hospital="Test Hospital",
            department="Oncology",
        )
        self.studio = DoctorStudio.objects.create(
            name="Director Studio",
            code="STU001",
            owner_doctor=self.director_profile,
        )
        self.director_profile.studio = self.studio
        self.director_profile.save(update_fields=["studio"])

        self.platform_user = CustomUser.objects.create_user(
            user_type=choices.UserType.DOCTOR,
            phone="13800138001",
            wx_nickname="Platform Doctor",
        )
        self.platform_profile = DoctorProfile.objects.create(
            user=self.platform_user,
            name="Platform Doctor",
            hospital="Test Hospital",
            department="Oncology",
            studio=self.studio,
        )

        self.assistant_user = CustomUser.objects.create_user(
            user_type=choices.UserType.ASSISTANT,
            phone="13800138002",
            wx_nickname="Assistant",
        )
        self.assistant_profile = AssistantProfile.objects.create(
            user=self.assistant_user,
            name="Assistant A",
        )
        self.assistant_profile.doctors.add(self.platform_profile)

        self.sales_user = CustomUser.objects.create_user(
            user_type=choices.UserType.SALES,
            phone="13800138003",
            wx_nickname="Sales",
        )
        self.sales_profile = SalesProfile.objects.create(
            user=self.sales_user,
            name="CRC A",
        )
        self.platform_profile.sales.add(self.sales_profile)

        self.patient_user = CustomUser.objects.create_user(
            user_type=choices.UserType.PATIENT,
            wx_openid="patient_openid_001",
            wx_nickname="Patient",
        )
        self.patient_profile = PatientProfile.objects.create(
            user=self.patient_user,
            phone="18600000001",
            name="Patient A",
            doctor=self.platform_profile,
        )

        self.family_user = CustomUser.objects.create_user(
            user_type=choices.UserType.PATIENT,
            wx_openid="family_openid_001",
            wx_nickname="Family",
        )
        self.family_relation = PatientRelation.objects.create(
            patient=self.patient_profile,
            user=self.family_user,
            relation_type=choices.RelationType.SPOUSE,
            name="Family A",
            relation_name="spouse",
            is_active=True,
        )

        self.assignment = PatientStudioAssignment.objects.create(
            patient=self.patient_profile,
            studio=self.studio,
            start_at=timezone.now(),
        )

        self.director_user_b = CustomUser.objects.create_user(
            user_type=choices.UserType.DOCTOR,
            phone="13800138010",
            wx_nickname="Director B",
        )
        self.director_profile_b = DoctorProfile.objects.create(
            user=self.director_user_b,
            name="Director B",
            hospital="Test Hospital",
            department="Oncology",
        )
        self.studio_b = DoctorStudio.objects.create(
            name="Director B Studio",
            code="STU002",
            owner_doctor=self.director_profile_b,
        )
        self.director_profile_b.studio = self.studio_b
        self.director_profile_b.save(update_fields=["studio"])

    def test_get_or_create_patient_conversation_uses_assignment(self):
        conversation = self.service.get_or_create_patient_conversation(
            self.patient_profile
        )
        self.assertEqual(conversation.type, ConversationType.PATIENT_STUDIO)
        self.assertEqual(conversation.patient_id, self.patient_profile.id)
        self.assertEqual(conversation.studio_id, self.studio.id)

        again = self.service.get_or_create_patient_conversation(self.patient_profile)
        self.assertEqual(conversation.id, again.id)

    def test_get_or_create_internal_conversation_unique(self):
        conversation = self.service.get_or_create_internal_conversation(
            self.patient_profile,
            self.studio,
            operator=self.platform_user,
        )
        self.assertEqual(conversation.type, ConversationType.INTERNAL)
        self.assertEqual(conversation.studio_id, self.studio.id)

        again = self.service.get_or_create_internal_conversation(
            self.patient_profile,
            self.studio,
            operator=self.platform_user,
        )
        self.assertEqual(conversation.id, again.id)

    def test_list_conversation_messages_with_after_before(self):
        conversation = self.service.get_or_create_patient_conversation(
            self.patient_profile
        )
        msg1 = self.service.create_text_message(
            conversation, self.patient_user, "hello"
        )
        msg2 = self.service.create_text_message(
            conversation, self.patient_user, "world"
        )

        after_messages = self.service.list_conversation_messages(
            conversation, after_id=msg1.id
        )
        self.assertEqual([msg2.id], [msg.id for msg in after_messages])

        before_messages = self.service.list_conversation_messages(
            conversation, before_id=msg2.id
        )
        self.assertEqual([msg1.id], [msg.id for msg in before_messages])

    def test_create_text_message_snapshot(self):
        conversation = self.service.get_or_create_patient_conversation(
            self.patient_profile
        )
        message = self.service.create_text_message(
            conversation, self.patient_user, "need help"
        )
        self.assertEqual(message.content_type, MessageContentType.TEXT)
        self.assertEqual(message.sender_id, self.patient_user.id)
        self.assertEqual(message.sender_display_name_snapshot, "Patient A")

        conversation.refresh_from_db()
        self.assertIsNotNone(conversation.last_message_at)

    def test_create_text_message_rejects_director(self):
        conversation = self.service.get_or_create_patient_conversation(
            self.patient_profile
        )
        with self.assertRaises(ValidationError):
            self.service.create_text_message(
                conversation, self.director_user, "not allowed"
            )

    def test_create_image_message_allows_platform_doctor(self):
        conversation = self.service.get_or_create_patient_conversation(
            self.patient_profile
        )
        image = build_test_image()
        message = self.service.create_image_message(
            conversation, self.platform_user, image
        )
        self.assertEqual(message.content_type, MessageContentType.IMAGE)
        self.assertTrue(message.image.name)

    def test_create_image_message_rejects_non_image(self):
        conversation = self.service.get_or_create_patient_conversation(
            self.patient_profile
        )
        fake_file = SimpleUploadedFile(
            "test.txt",
            b"not an image",
            content_type="text/plain",
        )
        with self.assertRaises(ValidationError):
            self.service.create_image_message(
                conversation, self.platform_user, fake_file
            )

    def test_forward_to_director_creates_internal_message(self):
        conversation = self.service.get_or_create_patient_conversation(
            self.patient_profile
        )
        original = self.service.create_text_message(
            conversation, self.patient_user, "symptom"
        )
        forwarded = self.service.forward_to_director(
            conversation,
            original.id,
            self.platform_user,
            note="urgent",
        )
        self.assertEqual(forwarded.conversation.type, ConversationType.INTERNAL)
        self.assertIn("urgent", forwarded.text_content)
        self.assertIn("symptom", forwarded.text_content)

    def test_mark_conversation_read_and_unread_count(self):
        conversation = self.service.get_or_create_patient_conversation(
            self.patient_profile
        )
        doc_msg = self.service.create_text_message(
            conversation, self.platform_user, "reply"
        )
        self.service.create_text_message(conversation, self.patient_user, "ok")

        self.service.mark_conversation_read(
            conversation, self.patient_user, last_message_id=doc_msg.id
        )
        unread = self.service.get_unread_count(conversation, self.patient_user)
        self.assertEqual(unread, 0)

    def test_get_unread_count_counts_only_other_senders(self):
        conversation = self.service.get_or_create_patient_conversation(
            self.patient_profile
        )
        self.service.create_text_message(conversation, self.platform_user, "reply")
        self.service.create_text_message(conversation, self.patient_user, "ok")

        unread = self.service.get_unread_count(conversation, self.patient_user)
        self.assertEqual(unread, 1)

    def test_get_unread_counts_multiple_conversations(self):
        patient_conversation = self.service.get_or_create_patient_conversation(
            self.patient_profile
        )
        internal_conversation = self.service.get_or_create_internal_conversation(
            self.patient_profile, self.studio
        )
        self.service.create_text_message(
            patient_conversation, self.patient_user, "question"
        )
        self.service.create_text_message(
            internal_conversation, self.platform_user, "internal note"
        )

        counts = self.service.get_unread_counts(
            self.director_user,
            [patient_conversation.id, internal_conversation.id],
        )
        self.assertEqual(counts[patient_conversation.id], 1)
        self.assertEqual(counts[internal_conversation.id], 1)

    def test_list_patient_conversation_summaries(self):
        conversation = self.service.get_or_create_patient_conversation(
            self.patient_profile
        )
        self.service.create_text_message(
            conversation, self.patient_user, "question"
        )

        summaries = self.service.list_patient_conversation_summaries(
            self.studio, self.director_user
        )
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0]["conversation_id"], conversation.id)
        self.assertEqual(summaries[0]["patient_id"], self.patient_profile.id)

    def test_transfer_patient_to_studio_updates_assignment_and_conversations(self):
        patient_conversation = self.service.get_or_create_patient_conversation(
            self.patient_profile
        )
        internal_conversation = self.service.get_or_create_internal_conversation(
            self.patient_profile, self.studio
        )

        new_assignment = self.service.transfer_patient_to_studio(
            self.patient_profile,
            self.studio_b,
            self.platform_user,
            reason="transfer",
        )
        self.assignment.refresh_from_db()
        self.assertIsNotNone(self.assignment.end_at)
        self.assertIsNone(new_assignment.end_at)
        self.assertEqual(new_assignment.studio_id, self.studio_b.id)

        patient_conversation.refresh_from_db()
        internal_conversation.refresh_from_db()
        self.assertEqual(patient_conversation.studio_id, self.studio_b.id)
        self.assertEqual(internal_conversation.studio_id, self.studio_b.id)

    def test_create_text_message_updates_conversation_session(self):
        conversation = self.service.get_or_create_patient_conversation(
            self.patient_profile
        )
        tz = timezone.get_current_timezone()
        time_1 = timezone.make_aware(datetime(2025, 1, 1, 9, 0), tz)
        time_2 = time_1 + timedelta(minutes=10)
        time_3 = time_2 + timedelta(minutes=31)

        with mock.patch("django.utils.timezone.now", return_value=time_1):
            self.service.create_text_message(conversation, self.patient_user, "one")
        with mock.patch("django.utils.timezone.now", return_value=time_2):
            self.service.create_text_message(conversation, self.patient_user, "two")
        with mock.patch("django.utils.timezone.now", return_value=time_3):
            self.service.create_text_message(conversation, self.patient_user, "three")

        sessions = list(
            ConversationSession.objects.filter(conversation=conversation).order_by(
                "start_at"
            )
        )
        self.assertEqual(len(sessions), 2)
        self.assertEqual(sessions[0].start_at, time_1)
        self.assertEqual(sessions[0].end_at, time_2)
        self.assertEqual(sessions[0].message_count, 2)
        self.assertEqual(sessions[1].start_at, time_3)
        self.assertEqual(sessions[1].end_at, time_3)

    def test_get_patient_chat_session_stats(self):
        conversation = self.service.get_or_create_patient_conversation(
            self.patient_profile
        )
        internal_conversation = self.service.get_or_create_internal_conversation(
            self.patient_profile,
            self.studio,
            operator=self.platform_user,
        )
        tz = timezone.get_current_timezone()
        time_1 = timezone.make_aware(datetime(2025, 1, 2, 6, 30), tz)
        time_2 = timezone.make_aware(datetime(2025, 1, 2, 8, 10), tz)
        time_3 = timezone.make_aware(datetime(2025, 1, 2, 22, 5), tz)
        time_4 = timezone.make_aware(datetime(2025, 2, 1, 9, 0), tz)

        ConversationSession.objects.create(
            conversation=conversation,
            patient=self.patient_profile,
            conversation_type=ConversationType.PATIENT_STUDIO,
            start_at=time_1,
            end_at=time_1,
            message_count=1,
        )
        ConversationSession.objects.create(
            conversation=conversation,
            patient=self.patient_profile,
            conversation_type=ConversationType.PATIENT_STUDIO,
            start_at=time_2,
            end_at=time_2,
            message_count=1,
        )
        ConversationSession.objects.create(
            conversation=conversation,
            patient=self.patient_profile,
            conversation_type=ConversationType.PATIENT_STUDIO,
            start_at=time_3,
            end_at=time_3,
            message_count=1,
        )
        ConversationSession.objects.create(
            conversation=internal_conversation,
            patient=self.patient_profile,
            conversation_type=ConversationType.INTERNAL,
            start_at=time_4,
            end_at=time_4,
            message_count=1,
        )

        stats = self.service.get_patient_chat_session_stats(
            patient=self.patient_profile,
            start_date=time_1.date(),
            end_date=time_3.date(),
        )

        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["monthly"], [{"month": "2025-01", "count": 3}])
        self.assertEqual(
            stats["time_slots"],
            {
                "0-7": 1,
                "7-10": 1,
                "10-13": 0,
                "13-18": 0,
                "18-21": 0,
                "21-24": 1,
            },
        )

    def test_get_patient_chat_session_stats_end_date_inclusive(self):
        conversation = self.service.get_or_create_patient_conversation(
            self.patient_profile
        )
        tz = timezone.get_current_timezone()
        end_of_day = timezone.make_aware(datetime(2025, 1, 1, 23, 59, 59), tz)
        next_day = timezone.make_aware(datetime(2025, 1, 2, 0, 0), tz)

        ConversationSession.objects.create(
            conversation=conversation,
            patient=self.patient_profile,
            conversation_type=ConversationType.PATIENT_STUDIO,
            start_at=end_of_day,
            end_at=end_of_day,
            message_count=1,
        )
        ConversationSession.objects.create(
            conversation=conversation,
            patient=self.patient_profile,
            conversation_type=ConversationType.PATIENT_STUDIO,
            start_at=next_day,
            end_at=next_day,
            message_count=1,
        )

        stats = self.service.get_patient_chat_session_stats(
            patient=self.patient_profile,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 1),
        )

        self.assertEqual(stats["total"], 1)
