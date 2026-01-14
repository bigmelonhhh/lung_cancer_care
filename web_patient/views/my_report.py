import json
import logging
import os
import uuid
from datetime import datetime

from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.urls import reverse
from django.core.paginator import Paginator

from health_data.models.test_report import TestReport
from users.decorators import auto_wechat_login, check_patient

logger = logging.getLogger(__name__)

@auto_wechat_login
@check_patient
def my_examination(request: HttpRequest) -> HttpResponse:
    """
    检查报告列表页面
    """
    patient = request.patient
    
    # 获取所有报告，按日期倒序
    reports = TestReport.objects.filter(patient=patient).order_by("-report_date", "-created_at")
    
    # 分页
    page_number = request.GET.get('page', 1)
    paginator = Paginator(reports, 20) # 每页20条
    page_obj = paginator.get_page(page_number)
    
    # 分组逻辑 (按日期分组)
    grouped_reports = []
    current_date = None
    current_group = None
    
    # 注意：分页是对 reports 进行的，所以我们只能对当前页的数据进行分组
    # 如果跨页导致同一天的报告被切分，这是分页的常见妥协。
    # 或者我们应该对"日期"进行分页？通常对 item 分页比较简单。
    
    for report in page_obj:
        # 处理图片URL
        images = report.image_urls
        if isinstance(images, str):
            try:
                images = json.loads(images)
            except json.JSONDecodeError:
                images = []
        elif not images:
            images = []
            
        # 展示所有图片
        preview_images = images
        
        if report.report_date != current_date:
            if current_group:
                grouped_reports.append(current_group)
            
            current_date = report.report_date
            current_group = {
                "date": current_date,
                "reports": [],
                "images": [], 
                "ids": [] 
            }
        
        current_group["reports"].append(report)
        # 这里我们将同一天的所有报告的图片都收集起来展示在这一天的卡片里？
        # 或者是每个 report 是一个独立的卡片？
        # 根据 UI 图 (Image 1)，似乎是按日期分组，然后显示一堆图片。
        # "上传日期: 2025-12-09" 下面有几张图。
        # 所以应该是按日期分组显示。
        current_group["images"].extend(preview_images)
        current_group["ids"].append(report.id)
        
    if current_group:
        grouped_reports.append(current_group)
        
    context = {
        "grouped_reports": grouped_reports,
        "page_obj": page_obj,
        "page_title": "检查报告"
    }
    return render(request, "web_patient/my_report_list.html", context)

@auto_wechat_login
@check_patient
def upload_report(request: HttpRequest) -> HttpResponse:
    """
    上传检查报告页面
    """
    if request.method == "POST":
        patient = request.patient
        report_date_str = request.POST.get("report_date")
        
        if not report_date_str:
            report_date = timezone.now().date()
        else:
            try:
                report_date = datetime.strptime(report_date_str, "%Y-%m-%d").date()
            except ValueError:
                report_date = timezone.now().date()
        
        # 处理图片上传
        image_files = request.FILES.getlist("images")
        image_urls = []
        
        if image_files:
            # 存储路径: examination_reports/patient_id/date/uuid.ext
            upload_dir = f"examination_reports/{patient.id}/{report_date}"
            
            for image_file in image_files:
                ext = os.path.splitext(image_file.name)[1]
                filename = f"{uuid.uuid4()}{ext}"
                file_path = f"{upload_dir}/{filename}"
                
                # 使用 default_storage 保存
                saved_path = default_storage.save(file_path, ContentFile(image_file.read()))
                # 获取 URL (假设配置了 MEDIA_URL)
                image_url = default_storage.url(saved_path)
                image_urls.append(image_url)
        
        if image_urls:
            # 创建报告
            # 这里我们假设一次上传创建一个 Report 对象，包含多张图
            TestReport.objects.create(
                patient=patient,
                report_date=report_date,
                image_urls=image_urls, # JSONField
                report_type=None # 用户未指定类型
            )
            # 模拟提交常规后回到列表页面，并且重新查询页面，分页参数重置查询
            return redirect("web_patient:report_list")

    context = {
        "today": timezone.now().date().strftime("%Y-%m-%d"),
        "page_title": "新增报告"
    }
    return render(request, "web_patient/my_report_upload.html", context)

@require_POST
@auto_wechat_login
@check_patient
def delete_report(request: HttpRequest) -> JsonResponse:
    """
    删除指定报告
    """
    patient = request.patient
    try:
        data = json.loads(request.body)
        report_ids = data.get("ids", [])
        
        # 允许删除单个或多个
        if not isinstance(report_ids, list):
            report_ids = [report_ids]
            
        if report_ids:
            TestReport.objects.filter(
                id__in=report_ids,
                patient=patient
            ).delete()
            
        return JsonResponse({"status": "success"})
    except Exception as e:
        logger.error(f"Failed to delete reports: {e}")
        return JsonResponse({"status": "error", "message": str(e)}, status=500)
