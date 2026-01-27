import logging
import random
import json
import os
import uuid
from datetime import date, timedelta, datetime, time
from typing import List, Dict, Any

from django.http import HttpRequest, HttpResponse, Http404, JsonResponse
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.db.models import Count, Q
from django.db.models.functions import TruncMonth

from users.models import PatientProfile
from users.decorators import check_doctor_or_assistant
from users.services.patient import PatientService
from users import choices as user_choices
from health_data.services.medical_history_service import MedicalHistoryService
from health_data.services.report_service import ReportArchiveService
from health_data.models import ClinicalEvent, ReportImage, ReportUpload
from market.service.order import get_paid_orders_for_patient
from core.service.treatment_cycle import (
    get_active_treatment_cycle,
    get_cycle_confirmer,
    get_treatment_cycles,
)
from core.service.tasks import MONITORING_ADHERENCE_ALL, get_adherence_metrics
from core.models import TreatmentCycle, choices, CheckupLibrary
from core.service.plan_item import PlanItemService
from core.service.checkup import get_active_checkup_library
from django.utils import timezone

logger = logging.getLogger(__name__)

def _get_checkup_timeline_data(patient: PatientProfile) -> dict:
    """
    获取复查诊疗时间轴数据（基于服务包时间范围）
    """
    # 1. 获取已支付订单以确定时间范围
    orders = get_paid_orders_for_patient(patient)
    
    start_date = None
    end_date = None
    
    # 逻辑：取最新（支付时间最晚）的一个有效服务包的时间范围
    if orders:
        latest_order = orders[0]
        start_date = latest_order.start_date
        end_date = latest_order.end_date
    
    # 默认兜底：如果没有服务包，或者服务包时间无效，显示过去12个月
    if not start_date or not end_date:
        today = date.today()
        end_date = today
        start_date = today - timedelta(days=365)

    # 2. 生成月份列表
    months_list = []
    curr = date(start_date.year, start_date.month, 1)
    end_month = date(end_date.year, end_date.month, 1)
    
    while curr <= end_month:
        months_list.append(curr)
        # 下个月
        if curr.month == 12:
            curr = date(curr.year + 1, 1, 1)
        else:
            curr = date(curr.year, curr.month + 1, 1)
            
    # 3. 批量查询数据
    events_qs = ClinicalEvent.objects.filter(patient=patient).filter(
        Q(event_date__gte=start_date, event_date__lte=end_date)
        | Q(event_date__isnull=True, created_at__date__gte=start_date, created_at__date__lte=end_date)
    ).values("id", "event_type", "event_date", "created_at")
    
    # 在内存中处理分组
    events_by_month = {}
    for event in events_qs:
        raw_report_date = event.get("event_date")
        report_date = None
        report_date_missing = False
        if isinstance(raw_report_date, datetime):
            report_date = raw_report_date.date()
        elif isinstance(raw_report_date, date):
            report_date = raw_report_date
        elif raw_report_date is None:
            report_date_missing = True
        else:
            report_date_missing = True
            logger.warning(
                "Invalid ClinicalEvent.event_date type, treat as missing. event_id=%s raw_type=%s",
                event.get("id"),
                type(raw_report_date).__name__,
            )

        created_at = event.get("created_at")
        tz = timezone.get_current_timezone()

        report_dt = None
        if report_date:
            report_dt = timezone.make_aware(datetime.combine(report_date, time.min), tz)

        created_dt = None
        if created_at:
            try:
                created_dt = timezone.localtime(created_at)
            except Exception:
                if isinstance(created_at, datetime):
                    created_dt = timezone.make_aware(created_at, tz) if timezone.is_naive(created_at) else created_at

        sort_dt = report_dt or created_dt or timezone.make_aware(datetime.combine(start_date, time.min), tz)
        display_dt = report_dt or created_dt or sort_dt
        try:
            display_dt_local = (
                timezone.localtime(display_dt)
                if isinstance(display_dt, datetime) and timezone.is_aware(display_dt)
                else display_dt
            )
        except Exception:
            display_dt_local = display_dt
        date_display = display_dt_local.strftime("%Y-%m-%d")

        if report_dt is None:
            report_date_missing = True

        m_key = sort_dt.strftime("%Y-%m")
        if m_key not in events_by_month:
            events_by_month[m_key] = []
        
        # 转换类型显示
        type_map = {1: "门诊", 2: "住院", 3: "复查"}
        type_code_map = {1: "outpatient", 2: "hospitalization", 3: "checkup"}
        
        events_by_month[m_key].append(
            {
                "id": event.get("id"),
                "type": type_code_map.get(event["event_type"], "other"),
                "type_display": type_map.get(event["event_type"], "其他"),
                "report_date_missing": report_date_missing,
                "created_at": created_at,
                "sort_dt": sort_dt,
                "date_display": date_display,
            }
        )

    def _safe_dt_ts(value):
        if not value:
            return 0
        try:
            return value.timestamp()
        except Exception:
            return 0

    # 4. 组装 timeline_data
    timeline_data = []
    for m_date in months_list:
        month_label = m_date.strftime("%Y-%m")
        
        # 智能显示年份：如果是列表第一个月，或者是一月份，显示年份
        if m_date == months_list[0] or m_date.month == 1:
            month_name = f"{m_date.year}年{m_date.month}月"
        else:
            month_name = f"{m_date.month}月"
        
        events = events_by_month.get(month_label, [])
        events.sort(
            key=lambda item: (
                _safe_dt_ts(item.get("sort_dt")),
                _safe_dt_ts(
                    timezone.localtime(item["created_at"])
                    if item.get("created_at")
                    else None
                ),
                item.get("id") or 0,
            ),
            reverse=True,
        )
        
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
        "timeline_data": timeline_data,
        "date_range": (start_date, end_date)
    }

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

    # 5. 复查诊疗时间轴数据（真实数据）
    timeline_result = _get_checkup_timeline_data(patient)
    timeline_data = timeline_result["timeline_data"]
    start_date, end_date = timeline_result["date_range"]

    # 默认选中当前月（如果在范围内），否则选中最后一个月
    # 注意：timeline_data 是按时间正序排列的
    today = date.today()
    if start_date and end_date and start_date <= today <= end_date:
        current_month_str = today.strftime("%Y-%m")
    elif timeline_data:
        # 默认选中最后一个月（通常是最新的）
        current_month_str = timeline_data[-1]["month_label"]
    else:
        current_month_str = today.strftime("%Y-%m")

    # NOTE: latest_reports（检查报告最新上传展示）功能已下线，不再在主页上下文中提供该字段。

    # 7. 获取复查分类二级数据
    try:
        checkup_lib = get_active_checkup_library()
        # 转换为前端友好的格式
        # get_active_checkup_library 返回 TypedDict，需用 key 访问
        checkup_subcategories = [item['name'] for item in checkup_lib]
    except Exception as e:
        logger.error(f"Failed to load checkup library: {e}")
        checkup_subcategories = []

    medication_adherence = get_adherence_metrics(
        patient_id=patient.id,
        adherence_type=choices.PlanItemCategory.MEDICATION,
    )
    monitoring_adherence = get_adherence_metrics(
        patient_id=patient.id,
        adherence_type=MONITORING_ADHERENCE_ALL,
    )

    def _format_adherence_display(metrics: dict) -> str:
        rate = metrics.get("rate")
        completed = metrics.get("completed", 0)
        total = metrics.get("total", 0)
        percent = "--" if rate is None else f"{rate * 100:.0f}%"
        return f"{percent}（{completed}/{total}）"

    medication_adherence_display = _format_adherence_display(medication_adherence)
    monitoring_adherence_display = _format_adherence_display(monitoring_adherence)

    adherence_start_date = medication_adherence.get("start_date")
    adherence_end_date = medication_adherence.get("end_date")
    adherence_date_range = ""
    if adherence_start_date and adherence_end_date:
        adherence_date_range = (
            f"{adherence_start_date.strftime('%Y-%m-%d')} ~ {adherence_end_date.strftime('%Y-%m-%d')}"
        )

    return {
        "served_days": served_days,
        "remaining_days": remaining_days,
        "doctor_info": doctor_info,
        "medical_info": medical_info,
        "patient": patient,
        "compliance": f"用药依从率{medication_adherence_display}，常规监测综合依从率{monitoring_adherence_display}",
        "medication_adherence": medication_adherence,
        "monitoring_adherence": monitoring_adherence,
        "medication_adherence_display": medication_adherence_display,
        "monitoring_adherence_display": monitoring_adherence_display,
        "adherence_date_range": adherence_date_range,
        "current_medication": current_medication,
        "timeline_data": timeline_data,
        "current_month": current_month_str,
        "checkup_subcategories": checkup_subcategories,
    }

@login_required
@check_doctor_or_assistant
def patient_checkup_timeline(request: HttpRequest, patient_id: int) -> HttpResponse:
    """
    Partial view to refresh the checkup timeline.
    """
    patient = get_object_or_404(PatientProfile, pk=patient_id)
    timeline_result = _get_checkup_timeline_data(patient)
    timeline_data = timeline_result["timeline_data"]
    start_date, end_date = timeline_result["date_range"]
    
    # Logic for default selected month (same as build_home_context)
    today = date.today()
    if start_date and end_date and start_date <= today <= end_date:
        current_month_str = today.strftime("%Y-%m")
    elif timeline_data:
        current_month_str = timeline_data[-1]["month_label"]
    else:
        current_month_str = today.strftime("%Y-%m")
    
    # 获取复查分类二级数据
    try:
        checkup_lib = get_active_checkup_library()
        checkup_subcategories = [item['name'] for item in checkup_lib]
    except Exception as e:
        logger.error(f"Failed to load checkup library: {e}")
        checkup_subcategories = []

    context = {
        "timeline_data": timeline_data,
        "current_month": current_month_str,
        "patient": patient,
        "checkup_subcategories": checkup_subcategories,
    }
    return render(request, "web_doctor/partials/home/checkup_timeline.html", context)

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
    
    history_list = get_checkup_history_data(context["patient"], filters)
        
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
            # // 可选：刷新页面或局部刷新
            # // location.reload(); 
            # // 或者弹出提示
            alert('用药方案已停止');
        </script>
    """)

@login_required
@check_doctor_or_assistant
@require_POST
def create_checkup_record(request: HttpRequest, patient_id: int) -> JsonResponse:
    """
    新增诊疗记录接口
    """
    patient = get_object_or_404(PatientProfile, pk=patient_id)
    
    # 1. 解析表单基本数据
    record_type_str = request.POST.get("record_type")
    report_date_str = request.POST.get("report_date")
    hospital = request.POST.get("hospital", "")
    remarks = request.POST.get("remarks", "")
    
    if not record_type_str or not report_date_str:
        return JsonResponse({"status": "error", "message": "缺少必填参数"}, status=400)
        
    # 映射记录类型
    type_map = {"门诊": 1, "住院": 2, "复查": 3}
    event_type = type_map.get(record_type_str)
    if not event_type:
        return JsonResponse({"status": "error", "message": "无效的记录类型"}, status=400)
        
    try:
        event_date = datetime.strptime(report_date_str, "%Y-%m-%d").date()
    except ValueError:
        return JsonResponse({"status": "error", "message": "日期格式错误"}, status=400)
        
    # 2. 解析文件及其元数据
    # 前端传递 files[] 数组和 file_metadata JSON 字符串
    # file_metadata 结构: [{"name": "filename", "category": "...", "subcategory": "..."}, ...]
    file_metadata_json = request.POST.get("file_metadata")
    if not file_metadata_json:
        return JsonResponse({"status": "error", "message": "缺少文件元数据"}, status=400)
        
    try:
        file_metadata_list = json.loads(file_metadata_json)
        # 转为以文件名(或索引)为key的字典，方便查找
        # 这里假设 metadata 顺序与 files 顺序一致，或者通过 name 匹配
        metadata_map = {m["name"]: m for m in file_metadata_list}
    except json.JSONDecodeError:
        return JsonResponse({"status": "error", "message": "元数据格式错误"}, status=400)
        
    files = request.FILES.getlist("files[]")
    if not files:
        # 尝试 'files' key
        files = request.FILES.getlist("files")
        
    if not files:
         return JsonResponse({"status": "error", "message": "请上传至少一张图片"}, status=400)
         
    # 3. 处理文件上传并构造 Service 参数
    image_payloads = []
    upload_dir = f"examination_reports/{patient.id}/{event_date}"
    
    # 预加载复查项目库，减少数据库查询
    checkup_libs = {lib.name: lib for lib in CheckupLibrary.objects.all()}
    
    try:
        for file in files:
            # 获取对应的元数据
            meta = metadata_map.get(file.name)
            if not meta:
                # 如果找不到名字匹配，尝试按顺序匹配（这就要求前端必须严格有序）
                # 暂时报错处理
                logger.warning(f"Missing metadata for file: {file.name}")
                continue
                
            category = meta.get("category")
            subcategory = meta.get("subcategory")
            
            # 保存文件
            ext = os.path.splitext(file.name)[1].lower()
            filename = f"{uuid.uuid4()}{ext}"
            file_path = f"{upload_dir}/{filename}"
            
            saved_path = default_storage.save(file_path, ContentFile(file.read()))
            image_url = default_storage.url(saved_path)
            
            payload = {
                "image_url": image_url,
            }
            
            # 处理复查项目逻辑
            if event_type == 3: # 复查
                if category == "复查" and subcategory:
                    lib_item = checkup_libs.get(subcategory)
                    if lib_item:
                        payload["checkup_item"] = lib_item
                    else:
                        # 如果找不到对应的复查项目，可能需要创建一个或者报错
                        # 这里暂时忽略或设为空，但 Service 层可能会校验
                        # Service check: if record_type == CHECKUP and not checkup_item: raise ValidationError
                        # 所以我们必须提供 checkup_item。如果名字匹配不上，可能是一个新项目？
                        # 为防止报错，如果找不到，我们可以尝试查找 "其他"
                        payload["checkup_item"] = checkup_libs.get("其他")
                else:
                    # 如果分类不是复查，但 event_type 是复查，这在业务逻辑上有点冲突
                    # 但 ReportArchiveService create_record_with_images 要求：
                    # if event_type == CHECKUP and not checkup_item: raise ValidationError
                    # 所以必须有 checkup_item
                    payload["checkup_item"] = checkup_libs.get("其他")
            
            image_payloads.append(payload)
            
        if not image_payloads:
             return JsonResponse({"status": "error", "message": "文件处理失败"}, status=400)

        # 4. 调用 Service
        doctor_profile = request.user.doctor_profile if hasattr(request.user, "doctor_profile") else None
        
        ReportArchiveService.create_record_with_images(
            patient=patient,
            created_by_doctor=doctor_profile,
            event_type=event_type,
            event_date=event_date,
            images=image_payloads,
            hospital_name=hospital,
            interpretation=remarks,
            uploader=request.user
        )
        
        return JsonResponse({"status": "success", "message": "创建成功"})
        
    except ValidationError as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)
    except Exception as e:
        logger.exception(f"Create checkup record failed: {e}")
        return JsonResponse({"status": "error", "message": "系统错误"}, status=500)
