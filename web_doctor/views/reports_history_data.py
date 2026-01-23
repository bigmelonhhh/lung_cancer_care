import random
import json
import os
import uuid
import logging
from typing import List, Dict, Any
from datetime import datetime

from django.http import HttpRequest, HttpResponse, Http404, JsonResponse
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.core.exceptions import ValidationError
from django.db.models import Prefetch, prefetch_related_objects
from django.utils import timezone

from users.decorators import check_doctor_or_assistant
from users.models import PatientProfile
from health_data.services.report_service import ReportUploadService, ReportArchiveService
from health_data.models import ReportImage, ClinicalEvent, ReportUpload
from health_data.models.report_upload import UploadSource
from core.service.checkup import get_active_checkup_library
from core.models import CheckupLibrary

logger = logging.getLogger(__name__)

# 预设图片分类
REPORT_IMAGE_CATEGORIES = [
    ("血常规", "血常规"),
    ("尿常规", "尿常规"),
    ("CT", "CT"),
    ("其他", "其他"),
]

# 记录类型定义
RECORD_TYPES = ["门诊", "住院", "复查"]

# 复查二级分类定义 (fallback)
RECHECK_SUB_CATEGORIES = [
    "血常规", "血生化", "胸部CT", "骨扫描", "头颅MR", "心脏彩超",
    "心电图", "凝血功能", "甲状腺功能", "肿瘤评估", "肿瘤标志物", "其他"
]

# 全局变量存储模拟数据 (仅保留图片档案部分的 Mock 逻辑，直到完全替换)
MOCK_ARCHIVE_DATA: List[Dict[str, Any]] = []

def _init_mock_archive_data():
    """初始化图片档案模拟数据 (仅用于图片档案 Tab，若已替换可移除)"""
    global MOCK_ARCHIVE_DATA
    if MOCK_ARCHIVE_DATA:
        return
    # ... (保持原有的 archive mock 数据生成逻辑，如果还需要的话)
    # 但根据代码，handle_reports_history_section 已经切换为真实数据 _get_archives_data
    # 所以这里其实不需要了。
    pass

def get_report_image_categories():
    """获取所有可用的图片分类"""
    return REPORT_IMAGE_CATEGORIES

def _map_clinical_event_to_dict(event: ClinicalEvent) -> Dict[str, Any]:
    """
    将 ClinicalEvent 映射为前端模板所需的数据结构
    """
    # 1. 处理图片
    # 注意：event.report_images 应该被 prefetch 以避免 N+1
    images = []
    
    # 尝试查找复查项目名称 (sub_category)
    sub_category = ""
    
    # 确保 event.report_images.all() 使用了 prefetch 的结果
    report_images = list(event.report_images.all())
    
    for img in report_images:
        # 构建分类显示
        category_str = ""
        type_map = {
            ReportImage.RecordType.OUTPATIENT: "门诊",
            ReportImage.RecordType.INPATIENT: "住院",
            ReportImage.RecordType.CHECKUP: "复查",
        }
        cat_name = type_map.get(img.record_type, "")
        
        if img.record_type == ReportImage.RecordType.CHECKUP and img.checkup_item:
            category_str = f"{cat_name}-{img.checkup_item.name}"
            # 顺便设置 sub_category (如果是复查类型)
            if not sub_category and event.event_type == ReportImage.RecordType.CHECKUP:
                sub_category = img.checkup_item.name
        else:
            category_str = cat_name
            
        images.append({
            "id": img.id,
            "name": f"图片-{img.id}",
            "url": img.image_url,
            "category": category_str,
            "report_date": img.report_date,
        })
        
    # 2. 处理归档人
    archiver_name = "-后台接口未定义"
    if getattr(event, "archiver_name", None) and event.archiver_name not in ("未知", ""):
        archiver_name = event.archiver_name
    elif event.created_by_doctor:
        archiver_name = event.created_by_doctor.name or event.created_by_doctor.user.username
        
    # 3. 处理归档日期
    archived_date_str = "-后台接口未定义"
    if event.created_at:
        archived_date_str = timezone.localtime(event.created_at).strftime("%Y-%m-%d")
        
    # 4. 记录类型映射
    record_type_map = {
        1: "门诊",
        2: "住院",
        3: "复查",
    }
    record_type_display = record_type_map.get(event.event_type, "-后台接口未定义")

    # 5. 处理上传人信息
    uploader_name = event.patient.name

    return {
        "id": event.id,
        "date": event.event_date,
        "images": images,
        "image_count": len(images),
        "interpretation": event.interpretation or "",
        "patient_info": {"name": event.patient.name, "age": event.patient.age},
        "uploader_info": {"name": uploader_name},
        "record_type": record_type_display,
        "sub_category": sub_category,
        "archiver": archiver_name,
        "archiver_name": archiver_name,
        "archived_date": archived_date_str,
        "status": "已完成", # 默认状态
    }

def _get_archives_data(patient: PatientProfile, page: int = 1, page_size: int = 10, start_date=None, end_date=None, category=None):
    """
    获取真实的图片档案数据
    """
    # 日期转换
    start_date_obj = None
    if start_date:
        if isinstance(start_date, str):
            try:
                start_date_obj = datetime.strptime(start_date, "%Y-%m-%d").date()
            except ValueError:
                pass
        else:
            start_date_obj = start_date

    end_date_obj = None
    if end_date:
        if isinstance(end_date, str):
            try:
                end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()
            except ValueError:
                pass
        else:
            end_date_obj = end_date

    logger.info(
        "image_archives _get_archives_data patient_id=%s page=%s page_size=%s start_date=%s end_date=%s",
        patient.id,
        page,
        page_size,
        start_date,
        end_date,
    )

    # 1. 调用 Service 获取分页后的上传记录
    uploads_page = ReportUploadService.list_uploads(
        patient=patient,
        include_deleted=False,
        upload_sources=[UploadSource.PERSONAL_CENTER, UploadSource.CHECKUP_PLAN],
        start_date=start_date_obj,
        end_date=end_date_obj,
        page=page,
        page_size=page_size
    )
    logger.info(
        "image_archives list_uploads patient_id=%s parsed_start=%s parsed_end=%s page=%s page_size=%s count=%s",
        patient.id,
        start_date_obj,
        end_date_obj,
        page,
        page_size,
        getattr(uploads_page.paginator, "count", None),
    )
    
    # 优化：预加载当前页关联的图片和诊疗记录
    upload_ids = [u.id for u in uploads_page.object_list]
    
    uploads_with_data = ReportUpload.objects.filter(id__in=upload_ids).prefetch_related(
        Prefetch(
            'images',
            queryset=ReportImage.objects.select_related('clinical_event', 'checkup_item', 'archived_by', 'archived_by__user').order_by('id')
        )
    ).order_by("-created_at")
    
    # 2. 遍历上传记录，按日期聚合图片
    grouped_archives: Dict[tuple, Dict[str, Any]] = {}
    
    for upload in uploads_with_data:
        upload_images = list(upload.images.all())
        if not upload_images:
            continue
            
        first_img = upload_images[0]
        local_created_at = timezone.localtime(upload.created_at)
        
        if first_img.report_date:
            group_date_key = first_img.report_date.strftime("%Y-%m-%d")
            display_date_str = local_created_at.strftime("%Y-%m-%d %H:%M:%S")
        else:
            group_date_key = local_created_at.strftime("%Y-%m-%d")
            display_date_str = local_created_at.strftime("%Y-%m-%d %H:%M:%S")

        group_key = (group_date_key, upload.upload_source)
        
        if group_key not in grouped_archives:
            grouped_archives[group_key] = {
                "id": f"group-{group_date_key}-{upload.upload_source}", 
                "date": display_date_str, 
                "images": [],
                "image_count": 0,
                "patient_info": {"name": patient.name, "age": patient.age},
                "upload_source": upload.get_upload_source_display(), 
                "is_archived": True, 
                "archiver": None,
                "archived_date": None,
                "record_type": "",
                "sub_category": "",
            }
            
        current_group = grouped_archives[group_key]
        
        for img in upload_images:
            category_str = ""
            if img.record_type:
                type_map = {
                    ReportImage.RecordType.OUTPATIENT: "门诊",
                    ReportImage.RecordType.INPATIENT: "住院",
                    ReportImage.RecordType.CHECKUP: "复查",
                }
                cat_name = type_map.get(img.record_type, "")
                category_str = cat_name
                
                if img.record_type == ReportImage.RecordType.CHECKUP and img.checkup_item:
                    category_str = f"{cat_name}-{img.checkup_item.name}"
            
            if not img.clinical_event:
                current_group["is_archived"] = False
            else:
                if not current_group["archiver"] and img.archived_by:
                    current_group["archiver"] = img.archived_by.name or img.archived_by.user.username
                if not current_group["archived_date"] and img.archived_at:
                    current_group["archived_date"] = img.archived_at.strftime("%Y-%m-%d")
                
                if not current_group["record_type"] and category_str:
                    parts = category_str.split("-")
                    current_group["record_type"] = parts[0]
                    if len(parts) > 1:
                        current_group["sub_category"] = parts[1]
            
            if not current_group["record_type"] and category_str:
                 parts = category_str.split("-")
                 current_group["record_type"] = parts[0]

            current_group["images"].append({
                "id": img.id,
                "name": f"图片-{img.id}", 
                "url": img.image_url,
                "category": category_str,
                "report_date": img.report_date.strftime("%Y-%m-%d") if img.report_date else "",
                "is_archived": bool(img.clinical_event)
            })
            
    for group in grouped_archives.values():
        group["image_count"] = len(group["images"])
    archives_list = sorted(list(grouped_archives.values()), key=lambda x: (x["date"], x["id"]), reverse=True)
    return archives_list, uploads_page


def handle_reports_history_section(request: HttpRequest, context: dict) -> str:
    """
    处理检查报告历史记录板块
    """
    import logging
    logger = logging.getLogger(__name__)
    
    template_name = "web_doctor/partials/reports_history/list.html"
    
    patient = context.get("patient")
    if not patient:
        logger.warning("handle_reports_history_section called without patient in context")
        return template_name 

    active_tab = request.GET.get("tab", "records")
    logger.info(f"Refreshing reports history section for patient {patient.id}, tab={active_tab}")
    
    try:
        records_page_num = int(request.GET.get("records_page", 1))
    except (TypeError, ValueError):
        records_page_num = 1
        
    try:
        images_page_num = int(request.GET.get("images_page", 1))
    except (TypeError, ValueError):
        images_page_num = 1
        
    record_type = request.GET.get("recordType") or request.GET.get("record_type")
    report_date_start = request.GET.get("reportDateStart") or request.GET.get("report_start_date")
    report_date_end = request.GET.get("reportDateEnd") or request.GET.get("report_end_date")
    archived_date_start = request.GET.get("archivedDateStart") or request.GET.get("archive_start_date")
    archived_date_end = request.GET.get("archivedDateEnd") or request.GET.get("archive_end_date")
    archiver = request.GET.get("archiver") or request.GET.get("archiver_name")
    images_start_date = request.GET.get("startDate") or ""
    images_end_date = request.GET.get("endDate") or ""
    logger.info(
        "image_archives request patient_id=%s startDate=%s endDate=%s images_page=%s",
        patient.id,
        images_start_date,
        images_end_date,
        images_page_num,
    )

    def _parse_date(value: str):
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return None

    report_start_date_obj = _parse_date(report_date_start)
    report_end_date_obj = _parse_date(report_date_end)
    archive_start_date_obj = _parse_date(archived_date_start)
    archive_end_date_obj = _parse_date(archived_date_end)
    
    # -----------------------------------------------------------
    # 处理诊疗记录数据 (Reports) - 切换为真实数据接口
    # -----------------------------------------------------------
    events_page = ReportArchiveService.list_clinical_events(
        patient=patient,
        record_type=record_type,
        report_start_date=report_start_date_obj,
        report_end_date=report_end_date_obj,
        archive_start_date=archive_start_date_obj,
        archive_end_date=archive_end_date_obj,
        archiver_name=archiver,
        page=records_page_num,
        page_size=10
    )
    # 预加载
    if events_page.object_list:
        prefetch_related_objects(
            events_page.object_list, 
            'report_images', 
            'report_images__checkup_item',
            'created_by_doctor',
            'created_by_doctor__user',
            'patient'
        )
    
    # 转换为前端所需的字典格式
    reports_list = [_map_clinical_event_to_dict(event) for event in events_page.object_list]
    
    # 替换 object_list 以便模板迭代
    events_page.object_list = reports_list
    reports_page = events_page
    
    # -----------------------------------------------------------
    # 处理图片档案数据 (Archives)
    # -----------------------------------------------------------
    archives_list, archives_page_obj = _get_archives_data(
        patient, 
        page=images_page_num,
        page_size=10,
        start_date=images_start_date, 
        end_date=images_end_date
    )

    # 动态获取复查二级分类
    try:
        checkup_lib = get_active_checkup_library()
        recheck_sub_categories = [item['name'] for item in checkup_lib]
    except Exception:
        recheck_sub_categories = RECHECK_SUB_CATEGORIES

    context.update({
        "reports_page": reports_page,
        "archives_list": archives_list,
        "archives_page_obj": archives_page_obj,
        "image_categories": get_report_image_categories(),  
        "record_types": RECORD_TYPES,
        "checkup_subcategories": recheck_sub_categories, 
        "active_tab": active_tab, 
        "filters": {
            "recordType": record_type or "",
            "reportDateStart": report_date_start or "",
            "reportDateEnd": report_date_end or "",
            "archivedDateStart": archived_date_start or "",
            "archivedDateEnd": archived_date_end or "",
            "archiver": archiver or "",
            "startDate": images_start_date,
            "endDate": images_end_date,
        }
    })
    return template_name

@login_required
@check_doctor_or_assistant
@require_POST
def batch_archive_images(request: HttpRequest, patient_id: int) -> HttpResponse:
    """
    批量归档图片 (保持不变，已使用真实 Service)
    """
    import json
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponse("无效的 JSON 数据", status=400)
        
    updates = data.get("updates")
    
    if not updates:
        image_ids = data.get("image_ids", [])
        category = data.get("category")
        report_date = data.get("report_date")
        if image_ids and category and report_date:
            updates = []
            for img_id in image_ids:
                updates.append({
                    "image_id": img_id,
                    "category": category,
                    "report_date": report_date
                })
    
    if not updates:
        return HttpResponse("参数不完整", status=400)
        
    service_updates = []
    checkup_libs = {lib.name: lib.id for lib in CheckupLibrary.objects.all()}
    
    for idx, update in enumerate(updates):
        img_id = update.get("image_id")
        category_str = update.get("category")
        report_date_str = update.get("report_date")
        if not img_id or not category_str or not report_date_str:
            return HttpResponse(f"第{idx + 1}条归档数据缺少必填字段", status=400)
            
        parts = str(category_str).split("-")
        type_name = parts[0]
        sub_name = parts[1] if len(parts) > 1 else None
        
        record_type = None
        if type_name == "门诊":
            record_type = ReportImage.RecordType.OUTPATIENT
        elif type_name == "住院":
            record_type = ReportImage.RecordType.INPATIENT
        elif type_name == "复查":
            record_type = ReportImage.RecordType.CHECKUP
        
        if record_type is None:
            return HttpResponse(f"第{idx + 1}条归档数据类目无效", status=400)
            
        checkup_item_id = None
        if record_type == ReportImage.RecordType.CHECKUP:
            if not sub_name:
                return HttpResponse(f"第{idx + 1}条归档数据缺少复查二级分类", status=400)
            checkup_item_id = checkup_libs.get(sub_name) or checkup_libs.get("其他")
            if not checkup_item_id:
                return HttpResponse(f"第{idx + 1}条归档数据复查二级分类无效", status=400)
        
        try:
            report_date = datetime.strptime(report_date_str, "%Y-%m-%d").date()
        except ValueError:
            return HttpResponse(f"第{idx + 1}条归档数据报告日期格式错误", status=400)
            
        service_updates.append({
            "image_id": img_id,
            "record_type": record_type,
            "report_date": report_date,
            "checkup_item_id": checkup_item_id
        })
        
    if not service_updates:
        return HttpResponse("无有效更新数据", status=400)
        
    doctor_profile = getattr(request.user, "doctor_profile", None)
    assistant_profile = getattr(request.user, "assistant_profile", None)
    
    archiver = None
    archiver_name = "未知"
    
    if doctor_profile:
        archiver = doctor_profile
        archiver_name = doctor_profile.name or "未知"
    elif assistant_profile:
        related_doctors = assistant_profile.doctors.all()
        if related_doctors.exists():
            archiver = related_doctors.first()
            archiver_name = assistant_profile.name or "未知"
        else:
            return HttpResponse("助理账号未关联任何医生，无法归档", status=403)
    else:
        return HttpResponse("非医生/助理账号无法归档", status=403)
         
    try:
        ReportArchiveService.archive_images(archiver, service_updates, archiver_name=archiver_name)
    except Exception as e:
        logger.exception("归档失败")
        return HttpResponse(f"归档失败: {str(e)}", status=400)
    
    patient = get_object_or_404(PatientProfile, pk=patient_id)
    context = {"patient": patient}
    
    request.GET._mutable = True
    request.GET["tab"] = "images"
    request.GET._mutable = False
    
    template_name = handle_reports_history_section(request, context)
    response = render(request, template_name, context)
    response["HX-Trigger"] = '{"show-toast": {"message": "归档保存成功", "type": "success"}}'
    
    return response

@login_required
@check_doctor_or_assistant
@require_POST
def patient_report_update(request: HttpRequest, patient_id: int, report_id: int) -> HttpResponse:
    """
    更新检查报告信息（包括图片分类、记录类型等）- 适配真实数据
    """
    import json

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponse("无效的 JSON 数据", status=400)

    image_updates = data.get("image_updates", [])
    record_type_str = data.get("record_type")
    sub_category_str = data.get("sub_category")
    interpretation = data.get("interpretation") # 前端也可能传这个
    
    # 获取 ClinicalEvent
    event = get_object_or_404(ClinicalEvent, pk=report_id, patient_id=patient_id)

    doctor_profile = getattr(request.user, "doctor_profile", None)
    assistant_profile = getattr(request.user, "assistant_profile", None)
    archiver = None
    archiver_name = "未知"
    if doctor_profile:
        archiver = doctor_profile
        archiver_name = doctor_profile.name or "未知"
    elif assistant_profile:
        related_doctors = assistant_profile.doctors.all()
        if related_doctors.exists():
            archiver = related_doctors.first()
            archiver_name = assistant_profile.name or "未知"
        else:
            return HttpResponse("助理账号未关联任何医生，无法归档", status=403)
    else:
        return HttpResponse("非医生/助理账号无法归档", status=403)

    updated_any = False

    if interpretation is not None:
        ReportArchiveService.update_clinical_event(event, interpretation=interpretation)
        updated_any = True

    type_map = {
        "门诊": ReportImage.RecordType.OUTPATIENT,
        "住院": ReportImage.RecordType.INPATIENT,
        "复查": ReportImage.RecordType.CHECKUP,
    }
    record_type = type_map.get(record_type_str) if record_type_str else event.event_type

    checkup_name_to_id = {lib.name: lib.id for lib in CheckupLibrary.objects.all()}
    service_updates = []
    for update in image_updates:
        img_id = update.get("image_id")
        category_str = update.get("category")
        if not img_id or not category_str:
            continue

        parts = str(category_str).split("-")
        type_name = parts[0]
        sub_name = parts[1] if len(parts) > 1 else None

        new_record_type = type_map.get(type_name)
        if new_record_type is None:
            continue

        payload = {
            "image_id": img_id,
            "record_type": new_record_type,
            "report_date": event.event_date,
        }
        if new_record_type == ReportImage.RecordType.CHECKUP:
            checkup_item_id = None
            if sub_name:
                checkup_item_id = checkup_name_to_id.get(sub_name)
            if not checkup_item_id:
                checkup_item_id = checkup_name_to_id.get("其他")
            if checkup_item_id:
                payload["checkup_item_id"] = checkup_item_id
        service_updates.append(payload)

    if record_type != event.event_type:
        event.event_type = record_type
        event.save(update_fields=["event_type"])
        updated_any = True

    if service_updates:
        try:
            ReportArchiveService.archive_images(archiver, service_updates, archiver_name=archiver_name)
            updated_any = True
        except ValidationError as e:
            return HttpResponse(str(e), status=400)
        except ClinicalEvent.MultipleObjectsReturned:
            logger.exception("保存失败")
            return HttpResponse("保存失败：检测到重复诊疗记录，请联系管理员处理数据", status=500)
        except Exception:
            logger.exception("保存失败")
            return HttpResponse("保存失败，请稍后重试", status=500)
    
    # 返回更新后的报告列表片段
    patient = get_object_or_404(PatientProfile, pk=patient_id)
    context = {"patient": patient}
    context["active_tab"] = "records" # 保持在记录 Tab
    
    template_name = handle_reports_history_section(request, context)
    
    response = render(request, template_name, context)
    
    if updated_any:
        response["HX-Trigger"] = '{"show-toast": {"message": "保存成功", "type": "success"}}'
        
    return response

@login_required
@check_doctor_or_assistant
@require_POST
def create_consultation_record(request: HttpRequest, patient_id: int) -> JsonResponse:
    """
    新增诊疗记录接口 (专用于 Reports History 模块)
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
    file_metadata_json = request.POST.get("file_metadata")
    if not file_metadata_json:
        return JsonResponse({"status": "error", "message": "缺少文件元数据"}, status=400)
        
    try:
        file_metadata_list = json.loads(file_metadata_json)
        metadata_map = {m["name"]: m for m in file_metadata_list}
    except json.JSONDecodeError:
        return JsonResponse({"status": "error", "message": "元数据格式错误"}, status=400)
        
    files = request.FILES.getlist("files[]")
    if not files:
        files = request.FILES.getlist("files")
        
    if not files:
         return JsonResponse({"status": "error", "message": "请上传至少一张图片"}, status=400)
         
    # 3. 处理文件上传并构造 Service 参数
    image_payloads = []
    upload_dir = f"examination_reports/{patient.id}/{event_date}"
    
    checkup_libs = {lib.name: lib for lib in CheckupLibrary.objects.all()}
    
    try:
        for file in files:
            meta = metadata_map.get(file.name)
            if not meta:
                logger.warning(f"Missing metadata for file: {file.name}")
                continue
                
            category = meta.get("category")
            subcategory = meta.get("subcategory")
            
            ext = os.path.splitext(file.name)[1].lower()
            filename = f"{uuid.uuid4()}{ext}"
            file_path = f"{upload_dir}/{filename}"
            
            saved_path = default_storage.save(file_path, ContentFile(file.read()))
            image_url = default_storage.url(saved_path)
            
            payload = {
                "image_url": image_url,
            }
            
            if event_type == 3: # 复查
                if category == "复查" and subcategory:
                    lib_item = checkup_libs.get(subcategory)
                    if lib_item:
                        payload["checkup_item"] = lib_item
                    else:
                        payload["checkup_item"] = checkup_libs.get("其他")
                else:
                    payload["checkup_item"] = checkup_libs.get("其他")
            
            image_payloads.append(payload)
            
        if not image_payloads:
             return JsonResponse({"status": "error", "message": "文件处理失败"}, status=400)

        # 4. 调用 Service
        doctor_profile = request.user.doctor_profile if hasattr(request.user, "doctor_profile") else None
        
        event = ReportArchiveService.create_record_with_images(
            patient=patient,
            created_by_doctor=doctor_profile,
            event_type=event_type,
            event_date=event_date,
            images=image_payloads,
            hospital_name=hospital,
            interpretation=remarks,
            uploader=request.user
        )
        return JsonResponse({"status": "success", "message": "创建成功", "event_id": event.id})
        
    except ValidationError as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)
    except Exception as e:
        logger.exception(f"Create consultation record failed: {e}")
        return JsonResponse({"status": "error", "message": "系统错误"}, status=500)


@login_required
@check_doctor_or_assistant
@require_POST
def delete_consultation_record(request: HttpRequest, patient_id: int, event_id: int) -> JsonResponse:
    patient = get_object_or_404(PatientProfile, pk=patient_id)
    event = get_object_or_404(ClinicalEvent, pk=event_id, patient=patient)

    try:
        updated_count = ReportArchiveService.delete_clinical_event(event)
        return JsonResponse(
            {
                "status": "success",
                "message": "删除成功",
                "event_id": event_id,
                "updated_images": updated_count,
            }
        )
    except Exception:
        logger.exception("Delete consultation record failed")
        return JsonResponse({"status": "error", "message": "删除失败，请稍后重试"}, status=500)
