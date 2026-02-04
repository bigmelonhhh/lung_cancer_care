from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from chat.models import Conversation, ConversationReadState, Message, ConversationType, MessageSenderRole
from users import choices as user_choices
from users.models import CustomUser, DoctorProfile, DoctorStudio, PatientProfile
from wx.models import SendMessageLog
from wx.services.chat_notifications import send_chat_unread_notification_for_message


class ChatUnreadNotificationTests(TestCase):
    def setUp(self):
        self.doctor_user = CustomUser.objects.create_user(
            user_type=user_choices.UserType.DOCTOR,
            phone="13800100000",
            wx_nickname="Doctor",
        )
        self.doctor_profile = DoctorProfile.objects.create(
            user=self.doctor_user,
            name="Doctor A",
            hospital="Test Hospital",
            department="Oncology",
        )
        self.studio = DoctorStudio.objects.create(
            name="Doctor Studio",
            code="STU_CHAT",
            owner_doctor=self.doctor_profile,
        )
        self.patient_user = CustomUser.objects.create_user(
            user_type=user_choices.UserType.PATIENT,
            wx_openid="patient_openid_chat",
            is_subscribe=True,
        )
        self.patient_profile = PatientProfile.objects.create(
            user=self.patient_user,
            phone="18600001000",
            name="Patient Chat",
        )
        self.conversation = Conversation.objects.create(
            patient=self.patient_profile,
            studio=self.studio,
            type=ConversationType.PATIENT_STUDIO,
        )

    def _create_message(
        self,
        *,
        sender_role,
        created_at_offset_seconds: int,
        sender: CustomUser | None = None,
    ) -> Message:
        msg = Message.objects.create(
            conversation=self.conversation,
            sender=sender or self.doctor_user,
            sender_role_snapshot=sender_role,
            sender_display_name_snapshot="Doctor",
            studio_name_snapshot=self.studio.name,
            text_content="hello",
        )
        created_at = timezone.now() - timedelta(seconds=created_at_offset_seconds)
        Message.objects.filter(pk=msg.id).update(created_at=created_at)
        msg.refresh_from_db()
        return msg

    def test_unread_message_sends_notification(self):
        message = self._create_message(
            sender_role=MessageSenderRole.PLATFORM_DOCTOR,
            created_at_offset_seconds=31,
        )
        with patch(
            "wx.services.chat_notifications._send_wechat_text",
            return_value=(True, None),
        ) as mock_send:
            sent = send_chat_unread_notification_for_message(message.id)

        self.assertTrue(sent)
        log = SendMessageLog.objects.get(scene=SendMessageLog.Scene.CHAT_UNREAD)
        self.assertEqual(log.channel, SendMessageLog.Channel.WECHAT)
        self.assertEqual(log.payload.get("message_id"), message.id)
        mock_send.assert_called_once()

    def test_no_notification_when_read(self):
        message = self._create_message(
            sender_role=MessageSenderRole.PLATFORM_DOCTOR,
            created_at_offset_seconds=31,
        )
        ConversationReadState.objects.create(
            conversation=self.conversation,
            user=self.patient_user,
            last_read_message=message,
        )
        with patch("wx.services.chat_notifications._send_wechat_text") as mock_send:
            sent = send_chat_unread_notification_for_message(message.id)

        self.assertFalse(sent)
        self.assertEqual(SendMessageLog.objects.count(), 0)
        mock_send.assert_not_called()

    def test_no_notification_for_patient_sender(self):
        message = self._create_message(
            sender_role=MessageSenderRole.PATIENT,
            created_at_offset_seconds=31,
            sender=self.patient_user,
        )
        with patch("wx.services.chat_notifications._send_wechat_text") as mock_send:
            sent = send_chat_unread_notification_for_message(message.id)

        self.assertFalse(sent)
        self.assertEqual(SendMessageLog.objects.count(), 0)
        mock_send.assert_not_called()

    def test_no_notification_when_not_subscribed(self):
        self.patient_user.is_subscribe = False
        self.patient_user.save(update_fields=["is_subscribe"])
        message = self._create_message(
            sender_role=MessageSenderRole.PLATFORM_DOCTOR,
            created_at_offset_seconds=31,
        )
        with patch("wx.services.chat_notifications._send_wechat_text") as mock_send:
            sent = send_chat_unread_notification_for_message(message.id)

        self.assertFalse(sent)
        self.assertEqual(SendMessageLog.objects.count(), 0)
        mock_send.assert_not_called()

    def test_no_notification_when_receive_wechat_message_disabled(self):
        self.patient_user.is_receive_wechat_message = False
        self.patient_user.save(update_fields=["is_receive_wechat_message"])
        message = self._create_message(
            sender_role=MessageSenderRole.PLATFORM_DOCTOR,
            created_at_offset_seconds=31,
        )
        with patch("wx.services.chat_notifications._send_wechat_text") as mock_send:
            sent = send_chat_unread_notification_for_message(message.id)

        self.assertFalse(sent)
        self.assertEqual(SendMessageLog.objects.count(), 0)
        mock_send.assert_not_called()

    def test_skip_when_already_sent(self):
        message = self._create_message(
            sender_role=MessageSenderRole.PLATFORM_DOCTOR,
            created_at_offset_seconds=31,
        )
        SendMessageLog.objects.create(
            patient=self.patient_profile,
            user=self.patient_user,
            openid=self.patient_user.wx_openid,
            channel=SendMessageLog.Channel.WECHAT,
            scene=SendMessageLog.Scene.CHAT_UNREAD,
            biz_date=timezone.localdate(),
            content="已推送",
            payload={"message_id": message.id},
            is_success=True,
        )
        with patch("wx.services.chat_notifications._send_wechat_text") as mock_send:
            sent = send_chat_unread_notification_for_message(message.id)

        self.assertFalse(sent)
        self.assertEqual(SendMessageLog.objects.count(), 1)
        mock_send.assert_not_called()

    def test_debounce_skips_duplicate_within_window(self):
        message = self._create_message(
            sender_role=MessageSenderRole.PLATFORM_DOCTOR,
            created_at_offset_seconds=31,
        )
        with patch(
            "wx.services.chat_notifications._acquire_debounce_lock",
            return_value=False,
        ) as mock_lock, patch(
            "wx.services.chat_notifications._send_wechat_text"
        ) as mock_send:
            sent = send_chat_unread_notification_for_message(message.id)

        self.assertFalse(sent)
        self.assertEqual(SendMessageLog.objects.count(), 0)
        mock_lock.assert_called_once()
        mock_send.assert_not_called()
