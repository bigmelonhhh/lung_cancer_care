import logging
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from users.models import PatientProfile
from core.models import TreatmentCycle
from datetime import date, timedelta
import random
from core.service.treatment_cycle import get_treatment_cycles
from health_data.services.questionnaire_submission import QuestionnaireSubmissionService
from core.models import Questionnaire
@login_required
def questionnaire_detail(request, patient_id):
    patient = get_object_or_404(PatientProfile, id=patient_id)
    


@login_required
def questionnaire_detail(request, patient_id):
    patient = get_object_or_404(PatientProfile, id=patient_id)
    
    # 获取选中的日期
    selected_date_str = request.GET.get('date')
    selected_date = None
    if selected_date_str:
        try:
            selected_date = date.fromisoformat(selected_date_str)
        except ValueError:
            pass

    # 1. 获取左侧历史记录数据
    history = []
    # 获取所有疗程
    cycles_page = get_treatment_cycles(patient, page=1, page_size=100)
    cycles = cycles_page.object_list
    
    logger = logging.getLogger(__name__)

    for cycle in cycles:
        # 获取该疗程时间范围内的提交日期
        logger.info(f"Processing Cycle ID={cycle.id} Name={cycle.name} Range={cycle.start_date}~{cycle.end_date}")
        
        dates = QuestionnaireSubmissionService.get_submission_dates(
            patient=patient,
            start_date=cycle.start_date,
            end_date=cycle.end_date
        )
        
        logger.info(f"  啊啊啊-> Found {len(dates)} submission dates: {dates}")
        
        history.append({
            "name": cycle.name,
            "is_current": False, 
            "dates": dates
        })

    # 如果没有选中日期，且有历史记录，默认选中第一条有日期的记录的第一个日期
    if not selected_date:
        for item in history:
            if item['dates']:
                selected_date = item['dates'][0]
                break
    
    # 2. 获取右侧详情数据
    # 改为动态列表，不再依赖预定义的 Key
    questionnaires = []
    
    if selected_date:
        # 获取当日问卷摘要列表
        summaries = QuestionnaireSubmissionService.list_daily_questionnaire_summaries(
            patient_id=patient.id,
            target_date=selected_date
        )
      
        
        for summary in summaries:
            submission_id = summary['submission_id']
            
            # 获取详细对比数据
            comparison = QuestionnaireSubmissionService.get_questionnaire_comparison(
                submission_id=submission_id
            )
            
            # 转换题目列表字段以适配模板
            questions = []
            for q_detail in comparison.get('questions', []):
                questions.append({
                    "text": q_detail.get('question_text'),
                    "current_answer": q_detail.get('current_answer'),
                    "prev_answer": q_detail.get('prev_answer'),
                    "change": q_detail.get('change_text'),
                    "change_type": q_detail.get('change_type')
                })
            
            # 构造完整的问卷模块数据对象
            # 确保包含用户要求的所有字段
            questionnaire_data = {
                "questionnaire_id": comparison.get('questionnaire_id'),
                "questionnaire_name": comparison.get('questionnaire_name'),
                "submission_id": comparison.get('submission_id'),
                "submitted_at": comparison.get('submitted_at'),
                
                "total_score": comparison.get('current_score'), # 对应 current_score
                "current_score": comparison.get('current_score'), # 保留旧字段兼容
                
                "prev_submission_id": comparison.get('prev_submission_id'),
                "prev_score": comparison.get('prev_score'),
                "prev_submitted_at": comparison.get('prev_submitted_at'),
                "prev_date": comparison.get('prev_date'),
                
                "score_change": comparison.get('score_change'),
                "change_type": comparison.get('change_type'),
                "change_text": comparison.get('change_text'),
                
                "questions": questions,
                "ai_summary": "" # 暂无 AI 摘要接口，置空
            }
            questionnaires.append(questionnaire_data)
    context = {
        "patient": patient,
        "selected_date": selected_date,
        "history": history,
        "questionnaires": questionnaires # 传递列表而非字典
    }
    
    # HTMX 请求处理：返回右侧详情内容，并附带左侧边栏更新 (OOB)
    if request.headers.get('HX-Request'):
        from django.template.loader import render_to_string
        
        # 渲染右侧详情内容
        content_html = render_to_string(
            "web_doctor/partials/indicators/_questionnaire_content.html", 
            context, 
            request=request
        )
        
        # 渲染左侧边栏内容 (为了更新选中高亮)
        sidebar_html = render_to_string(
            "web_doctor/partials/indicators/_questionnaire_sidebar.html", 
            context, 
            request=request
        )
        
        # 拼接返回：主内容 + 左侧OOB更新
        # 注意：左侧容器 ID 为 sidebar-container，我们在 _questionnaire_sidebar.html 
        # 外层并没有 ID，所以我们需要用 hx-swap-oob="innerHTML:#sidebar-container" 
        # 包裹 sidebar_html 或者在返回的 HTML 中构造一个带有 hx-swap-oob 属性的 div
        
        response_content = f"""
        {content_html}
        <div hx-swap-oob="innerHTML:#sidebar-container">
            {sidebar_html}
        </div>
        """
        return HttpResponse(response_content)

    return render(request, "web_doctor/partials/indicators/questionnaire_detail.html", context)
