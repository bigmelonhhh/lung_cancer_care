
import logging

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone

from chat.models.choices import MessageContentType
from chat.services.chat import ChatService
from patient_alerts.services.todo_list import TodoListService
from users import choices
from users.decorators import check_doctor_or_assistant
from users.models import PatientProfile

@login_required
@check_doctor_or_assistant
def mobile_home(request: HttpRequest) -> HttpResponse:
    logger = logging.getLogger(__name__)

    def get_positive_int(value, default: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default

    def format_cn_datetime(value):
        if not value:
            return ""
        try:
            dt = timezone.localtime(value) if timezone.is_aware(value) else value
            return f"{dt.year}年{dt.month}月{dt.day}日 {dt.strftime('%H:%M')}"
        except Exception:
            return ""

    def truncate_text(value: str, limit: int = 15) -> str:
        value = (value or "").strip()
        if len(value) <= limit:
            return value
        return value[:limit] + "......"

    def resolve_primary_studio(profile):
        if profile is None:
            return None
        if profile.studio is not None:
            return profile.studio
        owned_studios = list(profile.owned_studios.all())
        if owned_studios:
            return owned_studios[0]
        return None

    doctor_profile = getattr(request.user, "doctor_profile", None)
    assistant_profile = getattr(request.user, "assistant_profile", None)
    is_assistant = request.user.user_type == choices.UserType.ASSISTANT
    assistant_doctors_qs = None
    if assistant_profile is not None:
        assistant_doctors_qs = (
            assistant_profile.doctors.select_related("studio")
            .prefetch_related("owned_studios")
            .distinct()
        )
    acting_doctor_profile = doctor_profile
    if acting_doctor_profile is None and assistant_doctors_qs is not None:
        acting_doctor_profile = assistant_doctors_qs.first()

    if acting_doctor_profile is None:
        context = {
            "doctor": {
                "name": request.user.wx_nickname or request.user.username or "--",
                "title": "平台助理" if is_assistant else "--",
                "department": "--",
                "hospital": "--",
                "phone": getattr(request.user, "phone", "") or "--",
                "studio_name": "--",
                "avatar_url": None,
            },
            "stats": {
                "managed_patients": 0,
                "today_active": 0,
                "alerts_count": 0,
                "consultations_count": 0,
            },
            "alerts": [],
            "consultations": [],
            "doctor_error": "未找到医生档案信息，请联系管理员完善医生资料。",
            "is_director": False,
            "is_assistant": is_assistant,
            "show_department": False,
            "show_hospital": False,
            "show_my_assistant": False,
            "show_related_doctors": is_assistant,
        }
        return render(request, "web_doctor/mobile/index.html", context, status=404)

    studio = resolve_primary_studio(acting_doctor_profile)

    is_director = bool(
        doctor_profile is not None
        and studio is not None
        and studio.owner_doctor_id == doctor_profile.id
    )
    show_department = is_director
    show_hospital = is_director
    show_my_assistant = is_director
    show_related_doctors = is_assistant

    stats_doctor_ids: list[int] = []
    if is_assistant:
        display_name = (
            getattr(assistant_profile, "name", "")
            or request.user.wx_nickname
            or request.user.username
            or "--"
        )
        display_title = "平台助理"
        assistant_doctors = list(assistant_doctors_qs) if assistant_doctors_qs is not None else []
        stats_doctor_ids = [doctor.id for doctor in assistant_doctors]
        studio_names = []
        for doctor in assistant_doctors:
            doctor_studio = resolve_primary_studio(doctor)
            if doctor_studio and doctor_studio.name:
                studio_names.append(doctor_studio.name)
        studio_name_display = "、".join(sorted(set(studio_names))) if studio_names else "--"
    else:
        display_name = getattr(acting_doctor_profile, "name", "") or "--"
        doctor_title = getattr(acting_doctor_profile, "title", "") or ""
        display_title = f"({doctor_title})" if doctor_title else "--"
        stats_doctor_ids = [acting_doctor_profile.id]
        studio_name_display = getattr(studio, "name", "") if studio else "--"

    doctor_info = {
        "name": display_name,
        "title": display_title,
        "department": getattr(acting_doctor_profile, "department", "") or "--",
        "hospital": getattr(acting_doctor_profile, "hospital", "") or "--",
        "phone": getattr(request.user, "phone", "") or "--",
        "studio_name": studio_name_display,
        "avatar_url": None,
    }

    managed_patients = 0
    today_active = 0
    if stats_doctor_ids:
        patient_qs = PatientProfile.objects.filter(
            doctor_id__in=stats_doctor_ids,
            is_active=True,
        )
        managed_patients = patient_qs.count()
        # 业务要求：移动端首页“今日活跃”默认与“管理患者”保持一致。
        today_active = managed_patients

    alerts_page_number = get_positive_int(request.GET.get("alerts_page"), 1)
    alerts_page_size = get_positive_int(request.GET.get("alerts_size"), 1)
    # 移动端首页仅默认展示 1 条待办：避免信息过载，优先突出最需要立即处理的事项。
    alerts_page = TodoListService.get_todo_page(
        user=request.user,
        page=alerts_page_number,
        size=alerts_page_size,
        status=["pending", "escalate"],
    )
    alerts_count = alerts_page.paginator.count
    alerts = [
        {
            "id": item.get("id"),
            "patient_name": item.get("patient_name", ""),
            "type": item.get("event_title", ""),
            "time": format_cn_datetime(item.get("event_time")),
        }
        for item in alerts_page.object_list
    ]

    consultations: list[dict] = []
    consultations_count = 0
    if studio is not None:
        try:
            summaries = ChatService().list_patient_conversation_summaries(studio, request.user)
            unread_summaries = [s for s in summaries if (s.get("unread_count") or 0) > 0]
            consultations_count = len(unread_summaries)
            consultations_page_number = get_positive_int(request.GET.get("consultations_page"), 1)
            consultations_page_size = get_positive_int(request.GET.get("consultations_size"), 1)
            # 移动端首页仅默认展示 1 条咨询摘要：快速定位最新未读消息，更多内容由列表页承载。
            start_index = (consultations_page_number - 1) * consultations_page_size
            end_index = start_index + consultations_page_size
            for s in unread_summaries[start_index:end_index]:
                msg_type = s.get("last_message_type")
                if msg_type == MessageContentType.IMAGE:
                    content = "[图片]"
                else:
                    content = truncate_text(s.get("last_message_text", ""))
                consultations.append(
                    {
                        "id": s.get("conversation_id"),
                        "patient_name": s.get("patient_name", ""),
                        "content": content,
                        "time": format_cn_datetime(s.get("last_message_at")),
                    }
                )
        except ValidationError as e:
            logger.warning("加载移动端咨询摘要失败: %s", str(e))
        except Exception:
            logger.exception("加载移动端咨询摘要失败")

    stats = {
        "managed_patients": managed_patients,
        "today_active": today_active,
        "alerts_count": alerts_count,
        "consultations_count": consultations_count,
    }

    context = {
        "doctor": doctor_info,
        "stats": stats,
        "alerts": alerts,
        "consultations": consultations,
        "doctor_error": "",
        "is_director": is_director,
        "is_assistant": is_assistant,
        "show_department": show_department,
        "show_hospital": show_hospital,
        "show_my_assistant": show_my_assistant,
        "show_related_doctors": show_related_doctors,
    }

    return render(request, "web_doctor/mobile/index.html", context)
