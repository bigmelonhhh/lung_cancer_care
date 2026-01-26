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
from django.db import transaction

from health_data.models.report_upload import ReportUpload, ReportImage, UploadSource, UploaderRole
from health_data.services.report_service import ReportUploadService
from users.decorators import auto_wechat_login, check_patient, require_membership

logger = logging.getLogger(__name__)

@auto_wechat_login
@check_patient
@require_membership
def my_examination(request: HttpRequest) -> HttpResponse:
    """
    检查报告列表页面
    """
    patient = request.patient
    
    # 使用 Service 获取所有报告，按日期倒序（已分页）
    page_number = request.GET.get('page', 1)
    
    # 考虑到用户可能想看所有上传记录，我们查询该患者所有的上传批次。
    # ReportUploadService.list_uploads 返回的是 Page 对象
    page_obj = ReportUploadService.list_uploads(
        patient=patient,
        upload_sources=[UploadSource.PERSONAL_CENTER],
        page=page_number,
        page_size=20
    )
    
    # 分组逻辑 (按日期分组)
    grouped_reports = []
    current_date = None
    current_group = None
    
    for upload in page_obj:
        # 获取该批次下的所有图片
        images = upload.images.all()
        if not images.exists():
            continue
            
        # 确定该批次的显示日期
        # 优先使用第一张图片的 report_date，如果没有则使用 upload.created_at
        first_img = images.first()
        report_date = first_img.report_date if first_img and first_img.report_date else upload.created_at.date()
        
        # 提取所有图片 URL
        preview_images = [img.image_url for img in images]
        
        if report_date != current_date:
            if current_group:
                grouped_reports.append(current_group)
            
            current_date = report_date
            current_group = {
                "date": current_date,
                "reports": [], # 保留结构兼容
                "images": [], 
                "ids": [] 
            }
        
        # 将图片添加到当前日期组
        current_group["images"].extend(preview_images)
        # 记录 ReportUpload ID 用于删除
        current_group["ids"].append(upload.id)
        
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
@require_membership
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
        # 注意：前端可能传 images 或 images[]，Django request.FILES.getlist 处理多文件
        image_files = request.FILES.getlist("images")
        
        if image_files:
            try:
                with transaction.atomic():
                    # 准备调用 Service 的 payload
                    image_payloads = []
                    
                    # 存储路径: examination_reports/patient_id/date/uuid.ext
                    # 注意：这里使用 report_date 作为目录可能更好归档
                    upload_dir = f"examination_reports/{patient.id}/{report_date}"
                    
                    for image_file in image_files:
                        ext = os.path.splitext(image_file.name)[1].lower()
                        filename = f"{uuid.uuid4()}{ext}"
                        file_path = f"{upload_dir}/{filename}"
                        
                        # 保存文件
                        saved_path = default_storage.save(file_path, ContentFile(image_file.read()))
                        image_url = default_storage.url(saved_path)
                        
                        image_payloads.append({
                            "image_url": image_url,
                            # "record_type": '其他', # 默认为门诊/其他
                            "report_date": report_date
                        })
                    
                    if image_payloads:
                        # 调用 Service 创建
                        ReportUploadService.create_upload(
                            patient=patient,
                            images=image_payloads,
                            uploader=request.user,
                            upload_source=UploadSource.PERSONAL_CENTER,
                            uploader_role=UploaderRole.PATIENT
                        )
                        
                        return redirect("web_patient:report_list")
                        
            except Exception as e:
                logger.error(f"Failed to upload report: {e}")
                # 可以添加错误消息提示给用户
                # messages.error(request, "上传失败")
        
    context = {
        "today": timezone.now().date().strftime("%Y-%m-%d"),
        "page_title": "新增报告"
    }
    return render(request, "web_patient/my_report_upload.html", context)

@require_POST
@auto_wechat_login
@check_patient
@require_membership
def delete_report(request: HttpRequest) -> JsonResponse:
    """
    删除指定报告 (ReportUpload)
    """
    patient = request.patient
    try:
        data = json.loads(request.body)
        upload_ids = data.get("ids", [])
        
        # 允许删除单个或多个
        if not isinstance(upload_ids, list):
            upload_ids = [upload_ids]
            
        if upload_ids:
            # 查询待删除的记录，确保属于当前患者
            uploads = ReportUpload.objects.filter(
                id__in=upload_ids,
                patient=patient
            )
            
            # 逐个调用 Service 进行删除 (支持软删除逻辑)
            for upload in uploads:
                ReportUploadService.delete_upload(upload)
            
        return JsonResponse({"status": "success"})
    except Exception as e:
        logger.error(f"Failed to delete reports: {e}")
        return JsonResponse({"status": "error", "message": str(e)}, status=500)
