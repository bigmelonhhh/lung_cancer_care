from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from business_support.models import Device
from core.models import DailyTask, choices as core_choices
from users import choices as user_choices
from users.models import CustomUser, PatientProfile, PatientRelation
from wx.models import SendMessageLog
from wx.services.task_notifications import (
    send_daily_task_creation_messages,
    send_daily_task_reminder_messages,
)


class TaskNotificationTests(TestCase):
    def _create_patient(
        self,
        *,
        phone: str,
        openid: str,
        is_subscribe: bool = True,
        is_receive_wechat_message: bool = True,
        is_receive_watch_message: bool = True,
    ) -> PatientProfile:
        user = CustomUser.objects.create_user(
            wx_openid=openid,
            is_subscribe=is_subscribe,
            is_receive_wechat_message=is_receive_wechat_message,
            is_receive_watch_message=is_receive_watch_message,
        )
        return PatientProfile.objects.create(
            user=user,
            phone=phone,
            name="测试患者",
        )

    def _create_family_relation(
        self,
        *,
        patient: PatientProfile,
        openid: str,
        is_receive_wechat_message: bool = True,
    ) -> CustomUser:
        family_user = CustomUser.objects.create_user(
            wx_openid=openid,
            is_subscribe=True,
            is_receive_wechat_message=is_receive_wechat_message,
        )
        PatientRelation.objects.create(
            patient=patient,
            user=family_user,
            relation_type=user_choices.RelationType.CHILD,
            relation_name="家属",
            receive_alert_msg=True,
        )
        return family_user

    def _create_task(self, *, patient: PatientProfile, task_date, task_type) -> DailyTask:
        return DailyTask.objects.create(
            patient=patient,
            task_date=task_date,
            task_type=task_type,
            title="任务标题",
            detail="",
            status=core_choices.TaskStatus.PENDING,
        )

    def test_creation_sends_wechat_and_watch_logs_for_multi_task(self):
        today = timezone.localdate()
        patient = self._create_patient(phone="13800000001", openid="wx_openid_1")
        Device.objects.create(
            sn="SN001",
            imei="IMEI001",
            current_patient=patient,
        )
        self._create_task(
            patient=patient,
            task_date=today,
            task_type=core_choices.PlanItemCategory.MEDICATION,
        )
        self._create_task(
            patient=patient,
            task_date=today,
            task_type=core_choices.PlanItemCategory.CHECKUP,
        )

        with patch(
            "wx.services.task_notifications.SmartWatchService.send_message",
            return_value=(True, "msg123"),
        ) as mock_send:
            sent = send_daily_task_creation_messages(today)

        self.assertEqual(sent, 2)
        self.assertEqual(SendMessageLog.objects.count(), 2)

        wechat_log = SendMessageLog.objects.get(channel=SendMessageLog.Channel.WECHAT)
        watch_log = SendMessageLog.objects.get(channel=SendMessageLog.Channel.WATCH)

        self.assertEqual(wechat_log.user, patient.user)
        self.assertEqual(wechat_log.content, "已为您生成今日监测任务")
        self.assertIsNone(watch_log.user)
        self.assertEqual(watch_log.content, "已为您生成今日监测任务")
        self.assertEqual(watch_log.payload.get("msg_id"), "msg123")

        mock_send.assert_called_once_with("IMEI001", "今日任务", "已为您生成今日监测任务")

    def test_creation_sends_to_family_member(self):
        today = timezone.localdate()
        patient = self._create_patient(phone="13800000002", openid="wx_openid_2")
        family_user = self._create_family_relation(patient=patient, openid="wx_openid_family")
        self._create_task(
            patient=patient,
            task_date=today,
            task_type=core_choices.PlanItemCategory.MONITORING,
        )

        with patch("wx.services.task_notifications.SmartWatchService.send_message") as mock_send:
            sent = send_daily_task_creation_messages(today)

        self.assertEqual(sent, 2)
        self.assertEqual(SendMessageLog.objects.count(), 2)
        self.assertEqual(
            SendMessageLog.objects.filter(channel=SendMessageLog.Channel.WECHAT).count(),
            2,
        )
        self.assertEqual(
            SendMessageLog.objects.filter(user=patient.user).first().content,
            "已为您生成今日监测计划",
        )
        self.assertEqual(
            SendMessageLog.objects.filter(user=family_user).first().content,
            "已为您生成今日监测计划",
        )
        mock_send.assert_not_called()

    def test_reminder_respects_overdue_window(self):
        today = timezone.localdate()
        patient = self._create_patient(phone="13800000003", openid="wx_openid_3")
        self._create_task(
            patient=patient,
            task_date=today - timedelta(days=6),
            task_type=core_choices.PlanItemCategory.CHECKUP,
        )
        self._create_task(
            patient=patient,
            task_date=today - timedelta(days=1),
            task_type=core_choices.PlanItemCategory.MEDICATION,
        )

        with patch("wx.services.task_notifications.SmartWatchService.send_message") as mock_send:
            sent = send_daily_task_reminder_messages(today)

        self.assertEqual(sent, 1)
        self.assertEqual(SendMessageLog.objects.count(), 1)
        log = SendMessageLog.objects.first()
        self.assertEqual(log.channel, SendMessageLog.Channel.WECHAT)
        self.assertEqual(log.content, "您的复查任务未完成")
        mock_send.assert_not_called()

    def test_creation_skips_wechat_when_user_disabled(self):
        today = timezone.localdate()
        patient = self._create_patient(
            phone="13800000101",
            openid="wx_openid_disabled",
            is_subscribe=True,
            is_receive_wechat_message=False,
        )
        self._create_task(
            patient=patient,
            task_date=today,
            task_type=core_choices.PlanItemCategory.MONITORING,
        )

        with patch("wx.services.task_notifications.SmartWatchService.send_message") as mock_send:
            sent = send_daily_task_creation_messages(today)

        self.assertEqual(sent, 0)
        self.assertEqual(SendMessageLog.objects.count(), 0)
        mock_send.assert_not_called()

    def test_creation_skips_family_when_family_user_disabled(self):
        today = timezone.localdate()
        patient = self._create_patient(phone="13800000102", openid="wx_openid_102")
        self._create_family_relation(
            patient=patient,
            openid="wx_openid_family_disabled",
            is_receive_wechat_message=False,
        )
        self._create_task(
            patient=patient,
            task_date=today,
            task_type=core_choices.PlanItemCategory.MONITORING,
        )

        with patch("wx.services.task_notifications.SmartWatchService.send_message") as mock_send:
            sent = send_daily_task_creation_messages(today)

        self.assertEqual(sent, 1)
        self.assertEqual(SendMessageLog.objects.count(), 1)
        log = SendMessageLog.objects.first()
        self.assertEqual(log.channel, SendMessageLog.Channel.WECHAT)
        self.assertEqual(log.user, patient.user)
        mock_send.assert_not_called()

    def test_creation_skips_watch_when_watch_disabled(self):
        today = timezone.localdate()
        patient = self._create_patient(
            phone="13800000103",
            openid="wx_openid_watch_disabled",
            is_subscribe=True,
            is_receive_wechat_message=False,
            is_receive_watch_message=False,
        )
        Device.objects.create(
            sn="SN_WATCH_DISABLED",
            imei="IMEI_WATCH_DISABLED",
            current_patient=patient,
        )
        self._create_task(
            patient=patient,
            task_date=today,
            task_type=core_choices.PlanItemCategory.MONITORING,
        )

        with patch(
            "wx.services.task_notifications.SmartWatchService.send_message",
            return_value=(True, "msg123"),
        ) as mock_send:
            sent = send_daily_task_creation_messages(today)

        self.assertEqual(sent, 0)
        self.assertEqual(SendMessageLog.objects.count(), 0)
        mock_send.assert_not_called()
