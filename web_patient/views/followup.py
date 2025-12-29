import json
import logging
from django.shortcuts import render
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import ensure_csrf_cookie
from users.decorators import auto_wechat_login, check_patient
from core.service.questionnaire import QuestionnaireService
from health_data.services.questionnaire_submission import QuestionnaireSubmissionService
from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)

@auto_wechat_login
@check_patient
@ensure_csrf_cookie
def daily_survey(request: HttpRequest) -> HttpResponse:
    """
    【页面说明】今日随访问卷 `/p/followup/daily/`
    """
    # 1. 获取所有启用的问卷 ID
    active_questionnaires = QuestionnaireService.get_active_questionnaires()
    
    # 根据URL参数过滤问卷
    target_ids_str = request.GET.get('ids')
    if target_ids_str:
        try:
            target_ids = {int(i) for i in target_ids_str.split(',') if i.strip()}
            original_count = len(active_questionnaires)
            # 只保留在 active_questionnaires 中且在 target_ids 中的问卷
            active_questionnaires = [q for q in active_questionnaires if q.id in target_ids]
            logger.info(f"Filtered questionnaires for patient {request.patient.id}: {original_count} -> {len(active_questionnaires)}. Target IDs: {target_ids}")
        except ValueError:
            logger.warning(f"Invalid questionnaire IDs provided for patient {request.patient.id}: {target_ids_str}")

    survey_ids = [q.id for q in active_questionnaires]

    if not survey_ids:
        # 如果没有问卷，直接显示空状态或错误
        return render(request, "web_patient/followup/daily_survey.html", {
            "error": "暂无需要填写的随访问卷",
            "survey_ids": [],
            "all_surveys_data": None
        })

    # 2. 一次性获取所有问卷的详情数据
    all_surveys_data = QuestionnaireService.get_questionnaires_details(survey_ids)
    
    # 转换为以 ID 为 Key 的字典，方便前端查找，或者直接传列表

    context = {
        "survey_ids": json.dumps(survey_ids),
        "all_surveys_data": json.dumps(all_surveys_data),
        "total_count": len(survey_ids),
        "patient_id": request.patient.id,  # Add patient_id to context
    }

    return render(request, "web_patient/followup/daily_survey.html", context)

@auto_wechat_login
@check_patient
@require_GET
def get_survey_detail(request: HttpRequest, survey_id: int) -> JsonResponse:
    """
    API: 获取指定问卷的详情数据 (保留作为备用接口)
    """
    data = QuestionnaireService.get_questionnaire_detail(survey_id)
    if not data:
        return JsonResponse({"error": "问卷不存在"}, status=404)
    return JsonResponse(data)

@auto_wechat_login
@check_patient
@require_POST
def submit_surveys(request: HttpRequest) -> JsonResponse:
    """
    API: 提交单份问卷数据
    Payload: {
        "patient_id": 1,
        "questionnaire_id": 1,
        "answers": [{"option_id": 10}, ...]
    }
    """
    try:
        body = json.loads(request.body)
        
        # Validate patient_id
        req_patient_id = body.get("patient_id")
        if not req_patient_id or int(req_patient_id) != request.patient.id:
             return JsonResponse({"error": "患者ID不匹配或缺失"}, status=403)

        q_id = body.get("questionnaire_id")
        answers = body.get("answers", [])
        
        if not q_id:
             return JsonResponse({"error": "问卷ID缺失"}, status=400)

        # Call Service
        try:
            submission = QuestionnaireSubmissionService.submit_questionnaire(
                patient_id=request.patient.id,
                questionnaire_id=q_id,
                answers_data=answers
            )
            return JsonResponse({"success": True, "submission_id": submission.id})
        except ValidationError as e:
            return JsonResponse({"error": f"提交失败: {e.message}"}, status=400)

    except json.JSONDecodeError:
        return JsonResponse({"error": "无效的 JSON 数据"}, status=400)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
