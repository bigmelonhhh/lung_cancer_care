import logging
from datetime import datetime, timedelta
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from users.decorators import check_doctor_or_assistant
from web_doctor.views.workspace import _get_workspace_identities, _get_workspace_patients, get_user_display_name

from patient_alerts.services.todo_list import TodoListService
from patient_alerts.services.patient_alert import PatientAlertService
from patient_alerts.models import AlertStatus
from django.views.decorators.http import require_POST
from django.http import JsonResponse
import json

logger = logging.getLogger(__name__)

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
    
    # 接收筛选参数
    page = request.GET.get('page', 1)
    size = request.GET.get('size', 10)
    status = request.GET.get('status', 'all')
    start_date = request.GET.get('start_date', '')
    end_date = request.GET.get('end_date', '')
    
    # 调用 Service 获取真实数据
    todo_page = TodoListService.get_todo_page(
        user=request.user,
        page=page,
        size=size,
        status=status,
        start_date=start_date,
        end_date=end_date
    )
    
    context = {
        "doctor": doctor_profile,
        "assistant": assistant_profile,
        "workspace_display_name": display_name,
        "todo_page": todo_page,
        # 参数回显
        "current_status": status,
        "start_date": start_date,
        "end_date": end_date,
    }
    
    # HTMX 请求只返回列表部分
    if request.headers.get('HX-Request'):
        return render(request, "web_doctor/partials/todo_list/todo_list_table.html", context)
        
    return render(request, "web_doctor/partials/todo_list/todo_list.html", context)
