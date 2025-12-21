import logging
from django.http import HttpRequest, HttpResponse, Http404
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.core.exceptions import ValidationError

from users.models import PatientProfile
from users.decorators import check_doctor_or_assistant
from users.services.patient import PatientService
from health_data.services.medical_history_service import MedicalHistoryService

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

    return {
        "served_days": served_days,
        "remaining_days": remaining_days,
        "doctor_info": doctor_info,
        "medical_info": medical_info,
        "patient": patient,
        "compliance": "用药依从率86%，数据监测完成率68%"
    }

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
