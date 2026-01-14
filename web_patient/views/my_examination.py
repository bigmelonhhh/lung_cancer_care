import logging
from datetime import datetime

from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.db.models import Prefetch

from core.models import (
    DailyTask,
    TreatmentCycle,
)
from core.models.choices import PlanItemCategory, TaskStatus
from health_data.models.test_report import TestReport
from users.decorators import auto_wechat_login, check_patient

logger = logging.getLogger(__name__)


@auto_wechat_login
@check_patient
def my_examination(request: HttpRequest) -> HttpResponse:
    """
    我的复查页面
    展示按疗程分组的复查任务列表
    """
    patient = request.patient
    
    # 1. 获取所有疗程
    cycles = TreatmentCycle.objects.filter(patient=patient).order_by("-start_date")
    
    # 2. 获取所有检查类任务
    # 预加载关联的计划项和疗程，虽然我们主要通过逻辑分组
    tasks = DailyTask.objects.filter(
        patient=patient,
        task_type=PlanItemCategory.CHECKUP
    ).select_related("plan_item", "plan_item__cycle").order_by("-task_date")

    # 3. 数据分组逻辑
    # 结构: [{"cycle": cycle_obj, "name": "xxx", "is_current": bool, "tasks": [task_list]}]
    grouped_data = []
    
    # 将任务映射到疗程
    # 策略：
    # 1. 优先使用 task.plan_item.cycle
    # 2. 如果没有关联，尝试按时间范围匹配
    # 3. 否则归入"其他"
    
    tasks_by_cycle_id = {}
    unassigned_tasks = []
    
    for task in tasks:
        cycle = None
        if task.plan_item and task.plan_item.cycle:
            cycle = task.plan_item.cycle
        else:
            # 尝试按日期匹配
            for c in cycles:
                start = c.start_date
                end = c.end_date or timezone.now().date() # 如果没有结束日期，假设到今天（或者未来）
                if start <= task.task_date:
                    # 简单的匹配逻辑：任务日期在开始日期之后。
                    # 如果有多个疗程重叠（通常不应发生），这里取第一个匹配的（最新的）
                    cycle = c
                    break
        
        if cycle:
            if cycle.id not in tasks_by_cycle_id:
                tasks_by_cycle_id[cycle.id] = []
            tasks_by_cycle_id[cycle.id].append(task)
        else:
            unassigned_tasks.append(task)

    # 4. 构建前端视图数据
    today = timezone.now().date()
    
    for cycle in cycles:
        cycle_tasks = tasks_by_cycle_id.get(cycle.id, [])
        if not cycle_tasks:
            # 如果该疗程没有复查任务，也显示出来吗？通常显示，保持结构完整
            # 但如果没有任务，可能用户不关心。根据设计图，应该显示所有疗程
            # 这里我们只显示有任务的疗程，或者全部。设计图显示了"第三疗程"、"第二疗程"，即使状态不同。
            # 假设显示所有疗程
            pass
            
        # 处理任务状态展示逻辑
        processed_tasks = []
        for t in cycle_tasks:
            status_label = ""
            status_class = "" # 用于前端样式控制
            action_url = None
            is_actionable = False
            
            if t.status == TaskStatus.COMPLETED:
                status_label = "已完成"
                status_class = "text-sky-600" # 蓝色
                # 跳转到详情页
                # 假设详情页路由名为 web_patient:examination_detail
                action_url = "web_patient:examination_detail" 
            elif t.status == TaskStatus.PENDING:
                if t.task_date > today:
                    status_label = "未开始"
                    status_class = "text-slate-400" # 灰色
                else:
                    status_label = "去完成"
                    status_class = "text-indigo-600 font-semibold" # 强调色
                    action_url = "web_patient:record_checkup"
                    is_actionable = True
            
            # 如果疗程已终止，且任务未完成，是否显示为"已中止"？
            # 设计图显示"已中止"是灰色。
            # 这里我们根据任务状态判断。如果任务本身没有"TERMINATED"状态，
            # 可能需要根据疗程状态判断。
            # 但 DailyTask 没有 TERMINATED 状态。
            # 假设过期的未完成任务或者疗程终止的任务显示为已中止
            # 简单起见，如果疗程已终止且任务未完成，显示已中止
            # 或者如果任务关联的 plan_item 已停用
            
            # 这里简化逻辑：如果是过去的 Pending 任务，且不在"去完成"逻辑（比如很久以前），
            # 或者根据用户需求："未开始/未完成/已终止状态：仅显示数据"
            # 这里的"未完成"指红色那个。
            # 设计图：第二疗程有一项"未完成"（红色），一项"已中止"（灰色）。
            # 我们暂时只实现核心交互逻辑。
            
            processed_tasks.append({
                "obj": t,
                "label": status_label,
                "class": status_class,
                "action_url": action_url,
                "is_actionable": is_actionable
            })
            
        grouped_data.append({
            "cycle": cycle,
            "name": f"{cycle.name} (当前疗程)" if not cycle.end_date else cycle.name, # 简单模拟"当前"逻辑
            "tasks": processed_tasks
        })
        
    # 处理未归类任务
    if unassigned_tasks:
        processed_tasks = []
        for t in unassigned_tasks:
            # 同样的逻辑
            status_label = "未开始"
            status_class = "text-slate-400"
            action_url = None
            
            if t.status == TaskStatus.COMPLETED:
                status_label = "已完成"
                status_class = "text-sky-600"
                action_url = "web_patient:examination_detail"
            elif t.status == TaskStatus.PENDING:
                if t.task_date <= today:
                    status_label = "去完成"
                    status_class = "text-indigo-600 font-semibold"
                    action_url = "web_patient:record_checkup"
            
            processed_tasks.append({
                "obj": t,
                "label": status_label,
                "class": status_class,
                "action_url": action_url
            })
            
        grouped_data.append({
            "cycle": None,
            "name": "其他复查",
            "tasks": processed_tasks
        })

    context = {
        "grouped_data": grouped_data,
        "page_title": "我的复查"
    }
    return render(request, "web_patient/my_examination.html", context)


@auto_wechat_login
@check_patient
def examination_detail(request: HttpRequest, task_id: int) -> HttpResponse:
    """
    复查报告详情页面
    """
    patient = request.patient
    
    # 获取任务，确保属于当前患者
    task = get_object_or_404(DailyTask, id=task_id, patient=patient)
    
    # 获取关联的检查报告
    # 逻辑：通过 (patient, date) 关联 TestReport
    reports = TestReport.objects.filter(
        patient=patient,
        report_date=task.task_date
    )
    
    context = {
        "task": task,
        "reports": reports,
        "page_title": "复查详情"
    }
    return render(request, "web_patient/examination_detail.html", context)
