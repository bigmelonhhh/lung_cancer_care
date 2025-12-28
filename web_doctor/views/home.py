import logging
from django.http import HttpRequest, HttpResponse, Http404
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.core.exceptions import ValidationError

from users.models import PatientProfile
from users.decorators import check_doctor_or_assistant
from users.services.patient import PatientService
from users import choices as user_choices
from health_data.services.medical_history_service import MedicalHistoryService
from core.service.treatment_cycle import (
    get_active_treatment_cycle,
    get_cycle_confirmer,
    get_treatment_cycles,
)
from core.models import TreatmentCycle, choices
from core.service.plan_item import PlanItemService

logger = logging.getLogger(__name__)

def build_home_context(patient: PatientProfile) -> dict:
    """
    构建患者主页（概况）所需的数据上下文
    """
    # 1. 获取服务天数
    served_days, remaining_days = PatientService().get_guard_days(patient)

    # 2. 获取医生与工作室信息
    doctor_info = {
        "hospital": "--",
        "studio": "--"
    }
    if patient.doctor:
        doctor_info["hospital"] = patient.doctor.hospital or "--"
        if patient.doctor.studio:
            doctor_info["studio"] = patient.doctor.studio.name
        elif hasattr(patient.doctor, "owned_studios") and patient.doctor.owned_studios.exists():
            doctor_info["studio"] = patient.doctor.owned_studios.first().name

    # 3. 获取最新病情信息
    last_history = MedicalHistoryService.get_last_medical_history(patient)
    if last_history:
        medical_info = {
        "diagnosis": last_history.tumor_diagnosis if last_history.tumor_diagnosis is not None else "1",
        "risk_factors": last_history.risk_factors if last_history.risk_factors is not None else "2",
        "clinical_diagnosis": last_history.clinical_diagnosis if last_history.clinical_diagnosis is not None else "",
        "gene_test": last_history.genetic_test if last_history.genetic_test is not None else "",
        "history": last_history.past_medical_history if last_history.past_medical_history is not None else "",
        "surgery": last_history.surgical_information if last_history.surgical_information is not None else "",
        "last_updated": last_history.created_at.strftime("%Y-%m-%d") if last_history.created_at else "",  
        }
    else:
        medical_info = {
            "diagnosis": "",
            "risk_factors": "",
            "clinical_diagnosis": "",
            "gene_test": "",
            "history": "",
            "surgery": "",
            "last_updated": "",
        }
    
    # 注入备注信息（来自 PatientProfile）
    medical_info["remark"] = patient.remark or ""

    # 4. 获取当前用药数据（真实数据） 
    active_cycle = get_active_treatment_cycle(patient)
    current_medication = {}
    
    if active_cycle:
        # 1. 获取确认人信息（返回 CustomUser 对象和确认时间）
        confirmer, confirm_at = get_cycle_confirmer(active_cycle.id)
        
        # 2. 根据用户类型解析确认人姓名
        confirmer_name = "--"
        if confirmer:
            try:
                # 判断用户类型并获取对应档案的真实姓名
                if confirmer.user_type == user_choices.UserType.ASSISTANT:
                    # 医生助理类型：查询 AssistantProfile
                    if hasattr(confirmer, "assistant_profile") and confirmer.assistant_profile:
                        confirmer_name = "医生助理-"+confirmer.assistant_profile.name
                    else:
                        confirmer_name = "医生助理-"+confirmer.wx_nickname or "医生助理-"+confirmer.username or "未知助理"
                        
                elif confirmer.user_type == user_choices.UserType.DOCTOR:
                    # 医生类型：查询 DoctorProfile
                    if hasattr(confirmer, "doctor_profile") and confirmer.doctor_profile:
                        confirmer_name = "医生-"+confirmer.doctor_profile.name
                    else:
                        confirmer_name = "医生-"+confirmer.wx_nickname or "医生-"+confirmer.username or "未知医生"
                
                else:
                    # 其他类型：默认显示昵称或用户名
                    confirmer_name = getattr(confirmer, "name", "") or confirmer.wx_nickname or confirmer.username or "系统用户"
                    
            except Exception as e:
                # 5. 错误处理：防止因关联查询失败导致页面崩溃
                logger.error(f"获取确认人姓名失败 (User ID: {confirmer.id}): {e}")
                confirmer_name = "未知"

        plan_view = PlanItemService.get_cycle_plan_view(active_cycle.id)
        
        # 筛选出当前生效的药物
        active_meds = [m for m in plan_view["medications"] if m["is_active"]]
        
        
        items = []
        for med in active_meds:
            items.append({
                        "name": med["name"],
                        "frequency": med["current_usage"],  # 专业医学格式的频次提醒
                        "dosage": med["current_dosage"],
                        "usage": med.get("method_display", "")
                    })   
        current_medication = {
            "confirm_date": confirm_at.strftime("%Y-%m-%d") if confirm_at else "--",
            "confirmer": confirmer_name,
            "start_date": active_cycle.start_date.strftime("%Y-%m-%d"),
            "items": items
        }

    # 5. 模拟复查诊疗时间轴数据（当前月+前11个月）
    from datetime import date, timedelta
    
    today = date.today()
    timeline_data = []
    
    # 生成过去12个月的月份列表（倒序生成，然后反转以显示时间顺序）
    for i in range(11, -1, -1):
        # 计算月份偏移
        # 简单处理：每月按30天估算，用于生成月份标签
        target_date = today - timedelta(days=i*30)
        month_label = target_date.strftime("%Y-%m")
        month_name = f"{target_date.month}月"
        
        # 模拟事件数据
        events = []
        
        # 仅为部分月份添加模拟数据，制造差异感
        if i % 3 == 0:
             events.append({
                "type": "checkup",
                "type_display": "复查",
                "date": f"{target_date.year}-{target_date.month:02d}-02"
            })
        
        if i % 4 == 0:
            events.append({
                "type": "outpatient",
                "type_display": "门诊",
                "date": f"{target_date.year}-{target_date.month:02d}-04"
            })
            
        if i == 0: # 当前月添加住院记录
            events.append({
                "type": "hospitalization",
                "type_display": "住院",
                "date": f"{target_date.year}-{target_date.month:02d}-09"
            })

        # 统计计数
        checkup_count = sum(1 for e in events if e["type"] == "checkup")
        outpatient_count = sum(1 for e in events if e["type"] == "outpatient")
        hospitalization_count = sum(1 for e in events if e["type"] == "hospitalization")

        timeline_data.append({
            "month_label": month_label,
            "month_name": month_name,
            "events": events,
            "checkup_count": checkup_count,
            "outpatient_count": outpatient_count,
            "hospitalization_count": hospitalization_count
        })

    return {
        "served_days": served_days,
        "remaining_days": remaining_days,
        "doctor_info": doctor_info,
        "medical_info": medical_info,
        "patient": patient,
        "compliance": "用药依从率86%，数据监测完成率68%",
        "current_medication": current_medication,
        "timeline_data": timeline_data,
        "current_month": today.strftime("%Y-%m"),
        "latest_reports": {
            "upload_date": "2025-11-12 14:22",
            "images": [
                "https://placehold.co/200x200?text=Report+1",
                "https://placehold.co/200x200?text=Report+2",
                "https://placehold.co/200x200?text=Report+3",
                 "https://placehold.co/200x200?text=Report+1",
                "https://placehold.co/200x200?text=Report+2",
                "https://placehold.co/200x200?text=Report+3",
                 "https://placehold.co/200x200?text=Report+1",
                "https://placehold.co/200x200?text=Report+2",
                "https://placehold.co/200x200?text=Report+3",
                 "https://placehold.co/200x200?text=Report+1",
                "https://placehold.co/200x200?text=Report+2",
                "https://placehold.co/200x200?text=Report+3",
            ]
        }
    }

def get_checkup_history_data(filters: dict) -> list:
    """
    获取复查/诊疗历史记录模拟数据
    """
    import random
    from datetime import date, timedelta
    
    history_list = []
    
    types = ["checkup", "outpatient", "hospitalization"]
    operators = ["医生1", "医生2", "患者张三"]
    
    for i in range(25):  # 生成25条数据
        t = random.choice(types)
        base_date = date.today() - timedelta(days=i*5)
        
        # 简单的筛选过滤逻辑（模拟数据库查询）
        if filters["type"] and filters["type"] != t:
            continue
        if filters["start_date"] and str(base_date) < filters["start_date"]:
            continue
        if filters["end_date"] and str(base_date) > filters["end_date"]:
            continue
        
        operator = random.choice(operators)
        if filters["operator"] and filters["operator"] not in operator:
            continue

        history_list.append({
            "type": t,
            "event_date": base_date.strftime("%Y-%m-%d"),
            "record_date": (base_date + timedelta(days=1)).strftime("%Y-%m-%d"),
            "operator": operator,
            "can_delete": t != "checkup" or i % 2 == 0  # 模拟部分可删除
        })
    
    return history_list




def handle_checkup_history_section(request: HttpRequest, context: dict) -> str:
    """
    处理复查/诊疗历史记录板块
    """
    from django.core.paginator import Paginator
    
    template_name = "web_doctor/partials/checkup_history/list.html"
    # 获取筛选参数
    filters = {
        "type": request.GET.get("type", ""),
        "start_date": request.GET.get("start_date", ""),
        "end_date": request.GET.get("end_date", ""),
        "operator": request.GET.get("operator", ""),
    }
    
    history_list = get_checkup_history_data(filters)
        
    paginator = Paginator(history_list, 10)
    try:
        page = int(request.GET.get("page", 1))
    except (TypeError, ValueError):
        page = 1
        
    history_page = paginator.get_page(page)
    context.update({
        "history_page": history_page,
        "filters": filters
    })
    return template_name

def handle_medication_history_section(request: HttpRequest, context: dict) -> str:
    """
    处理历史用药方案板块
    """
    from django.core.paginator import Paginator

    patient = context.get("patient")
    if not patient:
         # Should not happen if context is built correctly, but safety check
         return "web_doctor/partials/medication_history/list.html"

    template_name = "web_doctor/partials/medication_history/list.html"
    
    try:
        page = int(request.GET.get("page", 1))
    except (TypeError, ValueError):
        page = 1

    # 获取分页的疗程列表
    qs = TreatmentCycle.objects.filter(patient=patient)
    # 过滤掉没有生效用药计划的疗程
    qs = qs.filter(
        plan_items__category=choices.PlanItemCategory.MEDICATION,
        plan_items__status=choices.PlanItemStatus.ACTIVE
    ).distinct()
    qs = qs.order_by("-start_date")
    
    paginator = Paginator(qs, 10)
    history_page = paginator.get_page(page)
    
    # 为每个疗程填充用药详情
    # 注意：history_page 是一个 Paginator Page 对象，object_list 包含 TreatmentCycle 实例
    # 我们直接修改实例属性以便在模板中访问
    
    for cycle in history_page:
        plan_view = PlanItemService.get_cycle_plan_view(cycle.id)
        active_meds = [m for m in plan_view["medications"] if m["is_active"]]
        
        items = []
        for med in active_meds:
            items.append({
                "name": med["name"],
                "frequency": med["current_usage"],
                "dosage": med["current_dosage"],
                "usage": med.get("method_display", "")
            })
        cycle.items = items
    
    context.update({
        "history_page": history_page,
    })
    return template_name

def handle_reports_history_section(request: HttpRequest, context: dict) -> str:
    """
    处理检查报告历史记录板块
    """
    from django.core.paginator import Paginator
    from web_doctor.views.reports_history_data import get_mock_reports_data
    
    template_name = "web_doctor/partials/reports_history/list.html"
    history_list = get_mock_reports_data()
    
    paginator = Paginator(history_list, 10)
    try:
        page = int(request.GET.get("page", 1))
    except (TypeError, ValueError):
        page = 1
    
    history_page = paginator.get_page(page)
    context.update({
        "history_page": history_page,
    })
    return template_name

@login_required
@check_doctor_or_assistant
@require_POST
def patient_home_remark_update(request: HttpRequest, patient_id: int) -> HttpResponse:
    """
    更新患者备注信息
    """
    try:
        patient = PatientProfile.objects.get(pk=patient_id)
    except PatientProfile.DoesNotExist:
        raise Http404("未找到患者")

    remark = request.POST.get("remark", "").strip()
    
    # 构造数据调用 Service 更新
    # 注意：save_patient_profile 需要 name 和 phone，这里我们需要透传原值以通过校验
    # 或者我们仅更新 remark 字段（如果 Service 支持局部更新最好，但 save_patient_profile 是全量更新）
    # 查看 Service 代码，它会检查 name 和 phone。因此我们需要构造完整 data
    
    data = {
        "name": patient.name,
        "phone": patient.phone,
        "gender": patient.gender,
        "birth_date": patient.birth_date,
        "address": patient.address,
        "ec_name": patient.ec_name,
        "ec_relation": patient.ec_relation,
        "ec_phone": patient.ec_phone,
        "remark": remark
    }

    try:
        PatientService().save_patient_profile(request.user, data, profile_id=patient.id)
    except ValidationError as exc:
        message = str(exc)
        response = HttpResponse(message, status=400)
        response["HX-Trigger"] = '{"plan-error": {"message": "%s"}}' % message.replace('"', '\\"')
        return response
    except Exception as exc:
        logger.exception(f"Error updating patient remark: {exc}")
        message = "系统错误"
        response = HttpResponse(message, status=500)
        response["HX-Trigger"] = '{"plan-error": {"message": "%s"}}' % message.replace('"', '\\"')
        return response

    # 更新成功，只返回备注部分的 HTML 片段或刷新整个概况区域
    # 为了体验更好，我们返回包含新备注的 span
    
    return HttpResponse(f"""
        <div id="patient-remark-display" class="flex items-center gap-2 group">
            <span class="text-slate-800 text-sm">{remark or '无'}</span>
            <button onclick="document.getElementById('edit-remark-modal').showModal()" class="text-indigo-600  transition-opacity">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"></path></svg>
            </button>
        </div>
        <script>document.getElementById('edit-remark-modal').close()</script>
    """)

@login_required
@check_doctor_or_assistant
@require_POST
def patient_medication_stop(request: HttpRequest, patient_id: int) -> HttpResponse:
    """
    停止当前用药方案（模拟接口）
    """
    # 实际逻辑应为：获取当前活跃的用药计划 -> 标记为停止 -> 记录日志等
    # 这里仅模拟操作，返回关闭弹框的脚本，并可能需要刷新区域（暂不处理刷新，仅关闭弹框）
    
    return HttpResponse("""
        <script>
            document.getElementById('stop-medication-modal').close();
            // 可选：刷新页面或局部刷新
            // location.reload(); 
            // 或者弹出提示
            alert('用药方案已停止');
        </script>
    """)
