from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from patient_alerts.models import AlertEventType, AlertLevel, AlertStatus, PatientAlert
from patient_alerts.services.patient_alert import PatientAlertService
from users import choices
from users.models import AssistantProfile, CustomUser, DoctorProfile, PatientProfile


class PatientAlertServiceTests(TestCase):
    def setUp(self):
        self.doctor_user = CustomUser.objects.create_user(
            user_type=choices.UserType.DOCTOR,
            phone="13800138111",
            wx_nickname="Dr. Handler",
        )
        self.doctor_profile = DoctorProfile.objects.create(
            user=self.doctor_user,
            name="处理医生",
            hospital="测试医院",
        )
        self.patient = PatientProfile.objects.create(
            phone="18600000222",
            doctor=self.doctor_profile,
        )
        self.alert = PatientAlert.objects.create(
            patient=self.patient,
            doctor=self.doctor_profile,
            event_type=AlertEventType.DATA,
            event_level=AlertLevel.MILD,
            event_title="血氧异常",
            event_content="血氧 94%",
            event_time=timezone.now(),
            status=AlertStatus.PENDING,
        )

    def test_update_status_sets_handler_content_and_history(self):
        handler = CustomUser.objects.create_user(
            user_type=choices.UserType.ASSISTANT,
            phone="13800138112",
            wx_nickname="助手",
        )
        handled_at = timezone.now()

        updated = PatientAlertService.update_status(
            alert_id=self.alert.id,
            status=AlertStatus.COMPLETED,
            handler_id=handler.id,
            handle_content="已联系患者，情况稳定。",
            handled_at=handled_at,
        )

        self.assertEqual(updated.status, AlertStatus.COMPLETED)
        self.assertEqual(updated.handler_id, handler.id)
        self.assertEqual(updated.handle_content, "已联系患者，情况稳定。")
        self.assertEqual(updated.handle_time, handled_at)
        self.assertEqual(updated.handle_meta["latest"]["status"], AlertStatus.COMPLETED)
        self.assertEqual(updated.handle_meta["latest"]["status_code"], "completed")
        self.assertEqual(updated.handle_meta["latest"]["handle_content"], "已联系患者，情况稳定。")
        self.assertEqual(
            updated.handle_meta["latest"]["handled_at"],
            timezone.localtime(handled_at).isoformat(),
        )
        self.assertEqual(updated.handle_meta["latest"]["handler_id"], handler.id)
        self.assertEqual(updated.handle_meta["latest"]["handler_name"], "助手")
        self.assertEqual(len(updated.handle_meta["history"]), 1)
        self.assertEqual(updated.handle_meta["history"][0], updated.handle_meta["latest"])

    def test_update_status_appends_history_without_overwriting_previous_records(self):
        first_handler = CustomUser.objects.create_user(
            user_type=choices.UserType.ASSISTANT,
            phone="13800138113",
            wx_nickname="助理A",
        )
        second_handler = CustomUser.objects.create_user(
            user_type=choices.UserType.DOCTOR,
            phone="13800138114",
            wx_nickname="医生B",
        )
        first_time = timezone.now() - timezone.timedelta(hours=1)
        second_time = timezone.now()

        PatientAlertService.update_status(
            alert_id=self.alert.id,
            status=AlertStatus.PENDING,
            handler_id=first_handler.id,
            handle_content="首次电话随访，继续观察。",
            handled_at=first_time,
        )
        updated = PatientAlertService.update_status(
            alert_id=self.alert.id,
            status=AlertStatus.COMPLETED,
            handler_id=second_handler.id,
            handle_content="二次复查后确认已完成。",
            handled_at=second_time,
        )

        self.assertEqual(updated.status, AlertStatus.COMPLETED)
        self.assertEqual(updated.handler_id, second_handler.id)
        self.assertEqual(updated.handle_content, "二次复查后确认已完成。")
        self.assertEqual(updated.handle_time, second_time)
        self.assertEqual(updated.handle_meta["latest"]["handler_name"], "医生B")
        self.assertEqual(
            updated.handle_meta["latest"]["handled_at"],
            timezone.localtime(second_time).isoformat(),
        )
        self.assertEqual(len(updated.handle_meta["history"]), 2)
        self.assertEqual(updated.handle_meta["history"][0]["handle_content"], "首次电话随访，继续观察。")
        self.assertEqual(updated.handle_meta["history"][0]["status_code"], "pending")
        self.assertEqual(updated.handle_meta["history"][1]["handle_content"], "二次复查后确认已完成。")
        self.assertEqual(updated.handle_meta["history"][1], updated.handle_meta["latest"])

    def test_update_status_with_no_handler_keeps_empty_handler_snapshot(self):
        handled_at = timezone.now()

        updated = PatientAlertService.update_status(
            alert_id=self.alert.id,
            status=AlertStatus.ESCALATED,
            handle_content="已升级主任处理。",
            handled_at=handled_at,
        )

        self.assertIsNone(updated.handler_id)
        self.assertEqual(updated.handle_meta["latest"]["handler_id"], None)
        self.assertEqual(updated.handle_meta["latest"]["handler_name"], "")
        self.assertEqual(updated.handle_meta["latest"]["status_code"], "escalate")
        self.assertEqual(
            updated.handle_meta["latest"]["handled_at"],
            timezone.localtime(handled_at).isoformat(),
        )

    def test_update_status_uses_now_and_repairs_invalid_handle_meta(self):
        self.alert.handle_meta = {"latest": "broken", "history": "broken"}
        self.alert.save(update_fields=["handle_meta"])

        before = timezone.now()
        updated = PatientAlertService.update_status(
            alert_id=self.alert.id,
            status=AlertStatus.COMPLETED,
            handle_content="系统已自动修复历史结构。",
        )
        after = timezone.now()

        self.assertIsNotNone(updated.handle_time)
        self.assertLessEqual(before, updated.handle_time)
        self.assertLessEqual(updated.handle_time, after)
        self.assertEqual(updated.handle_meta["latest"]["handle_content"], "系统已自动修复历史结构。")
        self.assertEqual(updated.handle_meta["latest"]["handled_at"], timezone.localtime(updated.handle_time).isoformat())
        self.assertEqual(len(updated.handle_meta["history"]), 1)

    def test_update_status_repairs_non_dict_handle_meta(self):
        self.alert.handle_meta = "broken"
        self.alert.save(update_fields=["handle_meta"])

        updated = PatientAlertService.update_status(
            alert_id=self.alert.id,
            status=AlertStatus.PENDING,
            handle_content="已修复非 dict 的 handle_meta。",
            handled_at=timezone.now(),
        )

        self.assertIsInstance(updated.handle_meta, dict)
        self.assertIsInstance(updated.handle_meta["latest"], dict)
        self.assertIsInstance(updated.handle_meta["history"], list)
        self.assertEqual(len(updated.handle_meta["history"]), 1)

    def test_update_status_repairs_partial_handle_meta_shapes(self):
        self.alert.handle_meta = {
            "latest": {"status": AlertStatus.PENDING, "handle_content": "旧记录"},
            "history": "broken",
        }
        self.alert.save(update_fields=["handle_meta"])

        updated = PatientAlertService.update_status(
            alert_id=self.alert.id,
            status=AlertStatus.COMPLETED,
            handle_content="已修复 history 结构。",
            handled_at=timezone.now(),
        )

        self.assertIsInstance(updated.handle_meta["latest"], dict)
        self.assertIsInstance(updated.handle_meta["history"], list)
        self.assertEqual(len(updated.handle_meta["history"]), 1)
        self.assertEqual(updated.handle_meta["latest"]["handle_content"], "已修复 history 结构。")

    def test_update_status_with_none_handle_content_keeps_latest_text_and_appends_history(self):
        first_time = timezone.now() - timezone.timedelta(minutes=30)
        second_time = timezone.now()

        PatientAlertService.update_status(
            alert_id=self.alert.id,
            status=AlertStatus.PENDING,
            handle_content="首次处理说明。",
            handled_at=first_time,
        )
        updated = PatientAlertService.update_status(
            alert_id=self.alert.id,
            status=AlertStatus.COMPLETED,
            handle_content=None,
            handled_at=second_time,
        )

        self.assertEqual(updated.handle_content, "首次处理说明。")
        self.assertEqual(len(updated.handle_meta["history"]), 2)
        self.assertEqual(updated.handle_meta["history"][0]["handle_content"], "首次处理说明。")
        self.assertEqual(updated.handle_meta["history"][1]["handle_content"], "首次处理说明。")
        self.assertEqual(updated.handle_meta["latest"]["status_code"], "completed")

    def test_update_status_prefers_doctor_profile_name_for_handler_name(self):
        doctor_user = CustomUser.objects.create_user(
            user_type=choices.UserType.DOCTOR,
            phone="13800138115",
            wx_nickname="昵称医生",
        )
        DoctorProfile.objects.create(
            user=doctor_user,
            name="主任医师张三",
            hospital="测试医院",
        )

        updated = PatientAlertService.update_status(
            alert_id=self.alert.id,
            status=AlertStatus.COMPLETED,
            handler_id=doctor_user.id,
            handle_content="医生已处理。",
            handled_at=timezone.now(),
        )

        self.assertEqual(updated.handle_meta["latest"]["handler_name"], "主任医师张三")

    def test_update_status_prefers_assistant_profile_name_for_handler_name(self):
        assistant_user = CustomUser.objects.create_user(
            user_type=choices.UserType.ASSISTANT,
            phone="13800138116",
            wx_nickname="昵称助理",
        )
        AssistantProfile.objects.create(
            user=assistant_user,
            name="助理李四",
        )

        updated = PatientAlertService.update_status(
            alert_id=self.alert.id,
            status=AlertStatus.COMPLETED,
            handler_id=assistant_user.id,
            handle_content="助理已处理。",
            handled_at=timezone.now(),
        )

        self.assertEqual(updated.handle_meta["latest"]["handler_name"], "助理李四")

    def test_update_status_invalid_status_raises(self):
        with self.assertRaises(ValidationError):
            PatientAlertService.update_status(
                alert_id=self.alert.id,
                status=999,
                handle_content="非法状态",
            )

    def test_update_status_invalid_alert_id_raises(self):
        with self.assertRaises(ValidationError):
            PatientAlertService.update_status(
                alert_id=999999,
                status=AlertStatus.COMPLETED,
                handle_content="记录不存在",
            )

    def test_get_detail_returns_alert(self):
        detail = PatientAlertService.get_detail(self.alert.id)
        self.assertEqual(detail.id, self.alert.id)
        self.assertEqual(detail.patient_id, self.patient.id)

    def test_get_detail_invalid_id_raises(self):
        with self.assertRaises(ValidationError):
            PatientAlertService.get_detail(999999)
