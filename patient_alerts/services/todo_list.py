from __future__ import annotations

from datetime import date, datetime, timedelta

from django.core.exceptions import ValidationError
from django.core.paginator import Page, Paginator
from django.utils import timezone

from core.models import QuestionnaireCode
from health_data.models import MetricType
from patient_alerts.models import AlertEventType, AlertLevel, AlertStatus, PatientAlert
from users.models import CustomUser, PatientProfile


_EVENT_TYPE_LABELS = {
    AlertEventType.DATA: "数据异常",
    AlertEventType.BEHAVIOR: "行为异常",
    AlertEventType.ARCHIVE: "新增档案",
    AlertEventType.QUESTIONNAIRE: "问卷异常",
    AlertEventType.OTHER: "其他",
}

_LEVEL_LABELS = {
    AlertLevel.MILD: "1级",
    AlertLevel.MODERATE: "2级",
    AlertLevel.SEVERE: "3级",
}

_STATUS_CODE_BY_VALUE = {
    AlertStatus.PENDING: "pending",
    AlertStatus.ESCALATED: "escalate",
    AlertStatus.COMPLETED: "completed",
}

_STATUS_VALUE_BY_CODE = {value: key for key, value in _STATUS_CODE_BY_VALUE.items()}

_STATUS_DISPLAY = {
    AlertStatus.PENDING: "待跟进",
    AlertStatus.ESCALATED: "升级主任",
    AlertStatus.COMPLETED: "已完成",
}

_MONITORING_TASK_TYPES = {
    MetricType.BODY_TEMPERATURE,
    MetricType.BLOOD_PRESSURE,
    MetricType.BLOOD_OXYGEN,
    MetricType.HEART_RATE,
    MetricType.WEIGHT,
    MetricType.STEPS,
    MetricType.USE_MEDICATED,
}


class TodoListService:
    """
    【功能说明】
    - 待办列表查询与分页服务（医生/医助视角）。
    - 提供筛选条件：状态、开始日期、结束日期。
    """

    @classmethod
    def get_todo_page(
        cls,
        *,
        user: CustomUser,
        page: int | str = 1,
        size: int | str = 10,
        status: str = "all",
        start_date: str | date | None = None,
        end_date: str | date | None = None,
        patient_id: int | str | None = None,
    ) -> Page:
        """
        获取待办事项分页结果。

        【参数说明】
        - user: 当前登录用户（医生/助理）。
        - page: 页码。
        - size: 每页数量。
        - status: 状态筛选（pending/escalate/completed/all）。
        - start_date: 开始日期（包含）。
        - end_date: 结束日期（包含）。
        - patient_id: 指定患者ID筛选。

        【返回值说明】
        - Page：分页对象，object_list 为列表数据。
        """
        page_num = cls._safe_int(page, default=1)
        page_size = cls._safe_int(size, default=10)

        qs = cls._build_base_queryset(user)
        
        if patient_id:
            pid = cls._safe_int(patient_id, default=0)
            if pid:
                qs = qs.filter(patient_id=pid)
                
        if status in _STATUS_VALUE_BY_CODE:
            qs = qs.filter(status=_STATUS_VALUE_BY_CODE[status])

        start_dt, end_dt = cls._parse_date_range(start_date, end_date)
        if start_dt:
            qs = qs.filter(event_time__gte=start_dt)
        if end_dt:
            qs = qs.filter(event_time__lt=end_dt)

        qs = qs.select_related("patient", "handler").order_by("-event_time", "-id")

        paginator = Paginator(qs, page_size)
        page_obj = paginator.get_page(page_num)
        page_obj.object_list = [cls._serialize_alert(alert) for alert in page_obj.object_list]
        return page_obj

    @classmethod
    def count_abnormal_events(
        cls,
        *,
        patient: PatientProfile,
        start_date: str | date,
        end_date: str | date,
        type: str | None = None,
        type_code: str | None = None,
    ) -> int:
        """
        统计患者在时间范围内的异常次数。

        【功能说明】
        - 按患者、时间区间统计异常记录数量。
        - type 支持监测指标（_MONITORING_TASK_TYPES）或问卷编码（QuestionnaireCode）。

        【使用方法】
        - TodoListService.count_abnormal_events(
              patient=patient,
              start_date="2025-01-01",
              end_date="2025-01-31",
              type=MetricType.BODY_TEMPERATURE,
          )
        - TodoListService.count_abnormal_events(
              patient=patient,
              start_date=date(2025, 1, 1),
              end_date=date(2025, 1, 31),
              type=QuestionnaireCode.Q_COUGH,
          )

        【参数说明】
        - patient: PatientProfile 实例。
        - start_date: str | date，开始日期（包含）。
        - end_date: str | date，结束日期（包含）。
        - type: str | None，监测指标或问卷编码。
        - type_code: str | None，type 的别名（优先级高于 type）。

        【返回值说明】
        - int：异常次数。

        【异常说明】
        - ValidationError：患者或类型无效、日期范围非法。
        """
        if not patient or not getattr(patient, "id", None):
            raise ValidationError("患者信息无效。")

        resolved_type = type_code or type
        if not resolved_type:
            raise ValidationError("type 不能为空。")

        start_dt, end_dt = cls._parse_date_range(start_date, end_date)
        if not start_dt or not end_dt:
            raise ValidationError("起止日期不能为空。")

        qs = PatientAlert.objects.filter(
            patient_id=patient.id,
            is_active=True,
        )

        if resolved_type in _MONITORING_TASK_TYPES:
            qs = qs.filter(
                event_type=AlertEventType.DATA,
                source_type="metric",
                source_payload__metric_type=resolved_type,
            )
        elif resolved_type in QuestionnaireCode.values:
            qs = qs.filter(
                event_type=AlertEventType.QUESTIONNAIRE,
                source_type="questionnaire",
                source_payload__questionnaire_code=resolved_type,
            )
        else:
            raise ValidationError("type 无效。")

        qs = qs.filter(event_time__gte=start_dt, event_time__lt=end_dt)
        return qs.count()

    @staticmethod
    def _build_base_queryset(user: CustomUser):
        doctor_profile = getattr(user, "doctor_profile", None)
        assistant_profile = getattr(user, "assistant_profile", None)
        if doctor_profile:
            return PatientAlert.objects.filter(
                is_active=True, patient__doctor=doctor_profile
            )
        if assistant_profile:
            doctors = assistant_profile.doctors.all()
            return PatientAlert.objects.filter(
                is_active=True, patient__doctor__in=doctors
            )
        return PatientAlert.objects.none()

    @staticmethod
    def _serialize_alert(alert: PatientAlert) -> dict:
        handler_name = TodoListService._get_user_display_name(alert.handler)
        patient_name = alert.patient.name if alert.patient_id else ""
        status_code = _STATUS_CODE_BY_VALUE.get(alert.status, "")
        return {
            "id": alert.id,
            "event_title": alert.event_title,
            "event_type": _EVENT_TYPE_LABELS.get(alert.event_type, alert.event_type),
            "event_level": _LEVEL_LABELS.get(alert.event_level, alert.event_level),
            "event_time": TodoListService._format_time(alert.event_time),
            "handle_time": TodoListService._format_time(alert.handle_time),
            "handler": handler_name,
            "status": status_code,
            "event_content": alert.event_content,
            "handle_content": alert.handle_content,
            "patient_name": patient_name,
            "status_display": _STATUS_DISPLAY.get(alert.status, ""),
        }

    @staticmethod
    def _parse_date_range(
        start_date: str | date | None, end_date: str | date | None
    ) -> tuple[datetime | None, datetime | None]:
        start = TodoListService._parse_date(start_date)
        end = TodoListService._parse_date(end_date)
        start_dt = None
        end_dt = None
        if start:
            start_dt = datetime.combine(start, datetime.min.time())
        if end:
            end_dt = datetime.combine(end + timedelta(days=1), datetime.min.time())
        if start_dt and timezone.is_aware(timezone.now()):
            start_dt = timezone.make_aware(start_dt)
        if end_dt and timezone.is_aware(timezone.now()):
            end_dt = timezone.make_aware(end_dt)
        return start_dt, end_dt

    @staticmethod
    def _parse_date(value: str | date | None) -> date | None:
        if isinstance(value, date):
            return value
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return None

    @staticmethod
    def _format_time(value: datetime | None) -> datetime | None:
        if not value:
            return None
        if timezone.is_naive(value):
            return value
        return timezone.localtime(value)

    @staticmethod
    def _safe_int(value: int | str, *, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _get_user_display_name(user: CustomUser | None) -> str:
        if not user:
            return ""
        doctor_profile = getattr(user, "doctor_profile", None)
        assistant_profile = getattr(user, "assistant_profile", None)

        if doctor_profile and getattr(doctor_profile, "name", ""):
            return doctor_profile.name
        if assistant_profile and getattr(assistant_profile, "name", ""):
            return assistant_profile.name

        if getattr(user, "wx_nickname", ""):
            return user.wx_nickname
        if getattr(user, "name", ""):
            return user.name
        if hasattr(user, "get_full_name") and user.get_full_name():
            return user.get_full_name()

        return getattr(user, "username", "") or getattr(user, "phone", "")
