import logging
import json
from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse, Http404
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_GET, require_POST

from users.decorators import check_doctor_or_assistant
from users import choices
from web_doctor.views.workspace import _get_workspace_identities, _get_workspace_patients, get_user_display_name

from patient_alerts.services.todo_list import TodoListService
from patient_alerts.services.patient_alert import PatientAlertService
from patient_alerts.models import AlertStatus
from django.http import JsonResponse

logger = logging.getLogger(__name__)

_STATUS_CODE_BY_VALUE = {
    AlertStatus.PENDING: "pending",
    AlertStatus.ESCALATED: "escalate",
    AlertStatus.COMPLETED: "completed",
}

_STATUS_DISPLAY_BY_CODE = {
    "pending": "待跟进",
    "escalate": "升级主任",
    "completed": "已完成",
}


def _format_history_handled_at(value: object) -> str:
    if not value:
        return ""

    dt = value if isinstance(value, datetime) else None
    if isinstance(value, str):
        dt = parse_datetime(value)

    if dt is None:
        return ""

    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return timezone.localtime(dt).strftime("%Y-%m-%d %H:%M")


def _get_status_code_from_snapshot(snapshot: dict) -> str:
    status_code = snapshot.get("status_code")
    if status_code in _STATUS_DISPLAY_BY_CODE:
        return status_code

    status_value = snapshot.get("status")
    try:
        status_value = int(status_value)
    except (TypeError, ValueError):
        return ""

    return _STATUS_CODE_BY_VALUE.get(status_value, "")


def _build_alert_history_payload(alert) -> list[dict[str, str]]:
    history_payload: list[dict[str, str]] = []

    handle_meta = alert.handle_meta if isinstance(alert.handle_meta, dict) else {}
    raw_history = handle_meta.get("history")
    if isinstance(raw_history, list):
        for entry in reversed(raw_history):
            if not isinstance(entry, dict):
                continue

            status_code = _get_status_code_from_snapshot(entry)
            status_display = _STATUS_DISPLAY_BY_CODE.get(status_code) or str(entry.get("status_display") or "")
            history_payload.append(
                {
                    "status_code": status_code,
                    "status_display": status_display,
                    "handle_content": str(entry.get("handle_content") or ""),
                    "handled_at": _format_history_handled_at(entry.get("handled_at")),
                    "handler_name": str(entry.get("handler_name") or ""),
                }
            )

    # 兼容历史老数据：没有 history，但已有处理内容/处理时间
    if not history_payload and (alert.handle_content or alert.handle_time):
        status_code = _STATUS_CODE_BY_VALUE.get(alert.status, "")
        history_payload.append(
            {
                "status_code": status_code,
                "status_display": _STATUS_DISPLAY_BY_CODE.get(status_code, ""),
                "handle_content": alert.handle_content or "",
                "handled_at": _format_history_handled_at(alert.handle_time),
                "handler_name": get_user_display_name(alert.handler),
            }
        )

    return history_payload


@login_required
@check_doctor_or_assistant
@require_GET
def doctor_todo_detail(request: HttpRequest) -> JsonResponse:
    alert_id = request.GET.get("id")
    try:
        alert_id = int(alert_id)
    except (TypeError, ValueError):
        return JsonResponse({"success": False, "message": "参数错误"}, status=400)

    try:
        alert = PatientAlertService.get_detail(alert_id)
    except ValidationError:
        return JsonResponse({"success": False, "message": "未找到待办"}, status=404)
    except Exception as exc:
        logger.error("查询待办详情失败: %s", str(exc), exc_info=True)
        return JsonResponse({"success": False, "message": "系统异常，请稍后重试"}, status=500)

    has_access = _get_workspace_patients(request.user, query=None).filter(pk=alert.patient_id).exists()
    if not has_access:
        return JsonResponse({"success": False, "message": "未找到待办"}, status=404)

    return JsonResponse(
        {
            "success": True,
            "data": {
                "id": alert.id,
                "history": _build_alert_history_payload(alert),
            },
        }
    )

@login_required
@check_doctor_or_assistant
@require_POST
def update_alert_status(request: HttpRequest) -> JsonResponse:
    """
    更新患者待办状态
    """
    try:
        data = json.loads(request.body)
        alert_id = data.get('id')
        status_code = data.get('status') # 'pending', 'escalate', 'completed'
        handle_content = data.get('handle_content')
        
        # 状态码转换映射
        STATUS_MAP = {
            'pending': AlertStatus.PENDING,
            'escalate': AlertStatus.ESCALATED,
            'completed': AlertStatus.COMPLETED
        }
        
        if status_code not in STATUS_MAP:
             return JsonResponse({'success': False, 'message': '无效的状态值'}, status=400)
             
        status_int = STATUS_MAP[status_code]
        
        PatientAlertService.update_status(
            alert_id=alert_id,
            status=status_int,
            handler_id=request.user.id,
            handle_content=handle_content
        )
        return JsonResponse({'success': True})
    except Exception as e:
        logger.error(f"更新待办状态失败: {str(e)}", exc_info=True)
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

@login_required
@check_doctor_or_assistant
def doctor_workspace(request: HttpRequest) -> HttpResponse:
    """
    医生工作台主视图（带待办事项功能）：
    - 左侧展示该医生名下患者列表（可搜索）
    - 右侧展示患者待办事项
    """
    # 待联调首页-患者待办列表：列表项包含事项分类、事项名称、事项报警内容、事项处理状态、事项创建时间
    # 获取基础上下文以保证页面布局正常（如左侧患者列表）
    doctor_profile, assistant_profile = _get_workspace_identities(request.user)
    patients = _get_workspace_patients(request.user, request.GET.get("q"))
    display_name = get_user_display_name(request.user)

    # 使用新的 getTodoList 获取数据 (取第一页前5条作为首页概览)
    # 注意：首页概览可能只需要少量数据，这里简化处理，直接调用
    # todo_page = getTodoList(request, page=1, size=5)

    # 为了兼容旧的模板变量名 todo_list，这里做个转换
    # 注意：todo_page 是 Page 对象，也可以迭代
    
    return render(
        request,
        "web_doctor/index.html",
        {
            "doctor": doctor_profile,
            "assistant": assistant_profile,
            "workspace_display_name": display_name,
            "patients": patients,
            "todo_list": [],  # 首页初始状态为空，点击患者后加载
        },
    )

@login_required
@check_doctor_or_assistant
def doctor_todo_list_page(request: HttpRequest) -> HttpResponse:
    """
    待办列表全屏页面
    """
    doctor_profile, assistant_profile = _get_workspace_identities(request.user)
    display_name = get_user_display_name(request.user)
    can_handle_todo = request.user.user_type == choices.UserType.ASSISTANT
    can_view_todo = request.user.user_type == choices.UserType.DOCTOR
    
    # 接收筛选参数
    page = request.GET.get('page', 1)
    size = request.GET.get('size', 10)
    status = request.GET.get('status', 'all')
    start_date = request.GET.get('start_date', '')
    end_date = request.GET.get('end_date', '')
    patient_id = request.GET.get('patient_id')
    todo_page = []
    if patient_id :
         # 调用 Service 获取真实数据
        todo_page = TodoListService.get_todo_page(
            user=request.user,
            page=page,
            size=size,
            status=status,
            start_date=start_date,
            end_date=end_date,
            patient_id=patient_id
        )
    context = {
        "doctor": doctor_profile,
        "assistant": assistant_profile,
        "workspace_display_name": display_name,
        "todo_page": todo_page,
        "can_handle_todo": can_handle_todo,
        "can_view_todo": can_view_todo,
        # 参数回显
        "current_status": status,
        "start_date": start_date,
        "end_date": end_date,
        "patient_id": patient_id,
    }
    
    # HTMX 请求只返回列表部分
    if request.headers.get('HX-Request'):
        return render(request, "web_doctor/partials/todo_list/todo_list_table.html", context)
        
    return render(request, "web_doctor/partials/todo_list/todo_list.html", context)


@login_required
@check_doctor_or_assistant
def patient_todo_sidebar(request: HttpRequest, patient_id: int) -> HttpResponse:
    """
    获取指定患者的待办事项侧边栏（局部刷新用）。
    """
    patients_qs = _get_workspace_patients(request.user, query=None)
    patient = patients_qs.filter(pk=patient_id).first()
    if patient is None:
        raise Http404("未找到患者")

    todo_page = TodoListService.get_todo_page(
        user=request.user,
        patient_id=patient.id,
        status="pending",
        page=1,
        size=5
    )
    
    return render(
        request,
        "web_doctor/partials/todo_list_sidebar.html",
        {
            "todo_list": todo_page.object_list,
            "current_patient": patient,
            "todo_total": todo_page.paginator.count,
            "can_handle_todo": request.user.user_type == choices.UserType.ASSISTANT,
        },
    )
