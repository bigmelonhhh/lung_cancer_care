import random
from typing import List, Dict, Any

from django.http import HttpRequest, HttpResponse, Http404
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator

from users.decorators import check_doctor_or_assistant
from users.models import PatientProfile

# 预设图片分类
REPORT_IMAGE_CATEGORIES = [
    ("血常规", "血常规"),
    ("尿常规", "尿常规"),
    ("CT", "CT"),
    ("其他", "其他"),
]

# 记录类型定义
RECORD_TYPES = ["门诊", "住院", "复查"]

# 复查二级分类定义
RECHECK_SUB_CATEGORIES = [
    "血常规", "血生化", "胸部CT", "骨扫描", "头颅MR", "心脏彩超",
    "心电图", "凝血功能", "甲状腺功能", "肿瘤评估", "肿瘤标志物", "其他"
]

# 全局变量存储模拟数据，实现内存级持久化
MOCK_REPORTS_DATA: List[Dict[str, Any]] = []
MOCK_ARCHIVE_DATA: List[Dict[str, Any]] = []

# TODO 1、待联调检查报告列表接口
# TODO 2、获取图片分类接口
# TODO 3、编辑接口-可以修改图片分类、报告解读内容
def _init_mock_data():
    """初始化模拟数据"""
    global MOCK_REPORTS_DATA, MOCK_ARCHIVE_DATA
    if MOCK_REPORTS_DATA and MOCK_ARCHIVE_DATA:
        return

    statuses = ["已完成", "待审核", "已打印"]
    archivers = ["小桃妖", "张三", "李四"]
    
    # 初始化诊疗记录数据 (Reports)
    for i in range(15):
        # 随机生成图片数量 (1-6张)
        img_count = random.randint(1, 6)
        images = []
        for j in range(img_count):
            images.append({
                "id": f"rep-{i}-{j}",
                "name": f"报告图片-{j+1}",
                "url": f"https://placehold.co/200x200?text=Report+{i}-{j}",
                "category": "其他"
            })
        
        date_str = f"2025-11-{12-i if 12-i > 0 else 1:02d}"
        
        MOCK_REPORTS_DATA.append({
            "id": 1000 + i,
            "date": date_str,
            "images": images,
            "image_count": len(images),
            "interpretation": f"这是关于报告 {i} 的解读内容。",
            "is_pushed": i % 2 == 0,
            "patient_info": {"name": "模拟患者", "age": 60},
            "record_type": random.choice(RECORD_TYPES),
            "sub_category": random.choice(RECHECK_SUB_CATEGORIES),
            "archiver": random.choice(archivers),
            "archived_date": date_str,
            "status": random.choice(statuses),
        })

    # 初始化图片档案数据 (Archives) - 独立的数据源
    # 图片档案通常是基于上传记录的，这里我们模拟另一组数据
    for i in range(20):
        img_count = random.randint(1, 4)
        images = []
        # 模拟日期（倒序排列）
        date_str = f"2025-10-{25-i if 25-i > 0 else 1:02d}"
        
        # 模拟来源
        upload_source = random.choice(["个人中心", "复查计划"])
        is_archived = True if upload_source == "复查计划" and random.random() > 0.2 else False
        
        if is_archived:
             archived_date = date_str
             archiver = random.choice(archivers)
        else:
             archived_date = None
             archiver = None
        
        for j in range(img_count):
            images.append({
                "id": f"arch-{i}-{j}",
                "name": f"档案图片-{j+1}",
                "url": f"https://placehold.co/200x200?text=Archive+{i}-{j}",
                "category": "其他" if is_archived else "",
                "report_date": date_str
            })

        MOCK_ARCHIVE_DATA.append({
            "id": 2000 + i,
            "date": date_str,
            "images": images,
            "image_count": len(images),
            "patient_info": {"name": "模拟患者", "age": 60},
            "upload_source": upload_source,
            "is_archived": is_archived,
            "archiver": archiver,
            "archived_date": archived_date,
            # 图片档案页面主要展示图片，不需要 record_type/sub_category 这种报告维度的强分类，
            # 但为了兼容模板逻辑，可以给默认值
            "record_type": "复查" if upload_source == "复查计划" else "",
            "sub_category": "",
        })

def get_mock_reports_data() -> List[Dict[str, Any]]:
    """获取诊疗记录模拟数据"""
    _init_mock_data()
    return MOCK_REPORTS_DATA

def get_mock_archives_data() -> List[Dict[str, Any]]:
    """获取图片档案模拟数据"""
    _init_mock_data()
    return MOCK_ARCHIVE_DATA


def update_report_image_category(report_id: int, image_id: str, new_category: str):
    """
    更新报告图片的分类
    """
    _init_mock_data()
    for report in MOCK_REPORTS_DATA:
        if report["id"] == report_id:
            for img in report["images"]:
                if img["id"] == image_id:
                    img["category"] = new_category
                    return True
    return False

def update_report_image_date(report_id: int, image_id: str, new_date: str):
    """
    更新报告图片的日期
    """
    _init_mock_data()
    for report in MOCK_REPORTS_DATA:
        if report["id"] == report_id:
            for img in report["images"]:
                if img["id"] == image_id:
                    img["report_date"] = new_date
                    return True
    return False
    
def update_report_record_info(report_id: int, record_type: str, sub_category: str):
    """
    更新报告的记录信息
    """
    _init_mock_data()
    for report in MOCK_REPORTS_DATA:
        if report["id"] == report_id:
            report["record_type"] = record_type
            report["sub_category"] = sub_category
            return True
    return False
    
def archive_report_images(updates: List[Dict], archiver_name: str):
    """
    批量归档图片 (支持差异化更新)
    updates: List of {image_id, category, report_date}
    """
    _init_mock_data()
    
    count = 0
    
    for update in updates:
        img_id = update.get("image_id")
        cat_info = update.get("category")
        r_date = update.get("report_date")
        
        if not img_id or not cat_info or not r_date:
            continue
            
        # 解析分类
        parts = cat_info.split("-")
        cat_type = parts[0]
        sub_cat = parts[1] if len(parts) > 1 else ""
        
        # 查找并更新 (在图片档案数据中查找)
        for report in MOCK_ARCHIVE_DATA:
            found = False
            for img in report["images"]:
                if img["id"] == img_id:
                    img["category"] = cat_info
                    img["report_date"] = r_date
                    found = True
                    count += 1
                    break
            
            if found:
                # 更新报告维度的状态
                all_archived = True
                for img in report["images"]:
                    if not img["category"]:
                        all_archived = False
                        break
                
                if all_archived:
                    report["is_archived"] = True
                    report["archived_date"] = r_date
                    report["archiver"] = archiver_name
                    report["record_type"] = cat_type
                    report["sub_category"] = sub_cat
                break
                
    return count

def get_report_image_categories():
    """获取所有可用的图片分类"""
    return REPORT_IMAGE_CATEGORIES

def handle_reports_history_section(request: HttpRequest, context: dict) -> str:
    """
    处理检查报告历史记录板块
    """
    template_name = "web_doctor/partials/reports_history/list.html"
    
    active_tab = request.GET.get("tab", "records")
    
    # 根据 Tab 获取不同的数据源 (同时处理两个分页)
    
    # 获取页码参数
    try:
        records_page_num = int(request.GET.get("records_page", 1))
    except (TypeError, ValueError):
        records_page_num = 1
        
    try:
        images_page_num = int(request.GET.get("images_page", 1))
    except (TypeError, ValueError):
        images_page_num = 1
    
    # 处理诊疗记录数据
    reports_list = get_mock_reports_data()
    reports_paginator = Paginator(reports_list, 10)
    reports_page = reports_paginator.get_page(records_page_num)
    
    # 处理图片档案数据
    archives_list = get_mock_archives_data()
    archives_paginator = Paginator(archives_list, 15)
    archives_page = archives_paginator.get_page(images_page_num)

    context.update({
        "reports_page": reports_page,
        "archives_page": archives_page,
        "image_categories": get_report_image_categories(),
        "record_types": RECORD_TYPES,
        "recheck_sub_categories": RECHECK_SUB_CATEGORIES,
        "active_tab": active_tab, # 传递当前 tab
    })
    return template_name

@login_required
@check_doctor_or_assistant
@require_POST
def batch_archive_images(request: HttpRequest, patient_id: int) -> HttpResponse:
    """
    批量归档图片 (支持每张图片独立设置)
    Payload: { updates: [{image_id, category, report_date}, ...] }
    兼容旧格式: { image_ids: [], category, report_date }
    """
    import json
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponse("无效的 JSON 数据", status=400)
        
    updates = data.get("updates")
    
    # 兼容旧接口格式 (如果前端还未完全切换)
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
        
    # 执行归档
    archive_report_images(updates, request.user.doctor_profile.name if hasattr(request.user, 'doctor_profile') else "医生")
    
    patient = get_object_or_404(PatientProfile, pk=patient_id)
    context = {"patient": patient}
    
    # 刷新页面，保持在 images tab
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
    更新检查报告信息（包括图片分类、记录类型等）
    """
    import json

    # 解析 JSON 数据
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponse("无效的 JSON 数据", status=400)

    image_updates = data.get("image_updates", [])
    record_type = data.get("record_type")
    sub_category = data.get("sub_category")
    
    updated_any = False
    
    # 更新记录类型
    if record_type:
        if update_report_record_info(report_id, record_type, sub_category):
             updated_any = True

    # 批量更新图片分类
    for update in image_updates:
        image_id = update.get("image_id")
        new_category = update.get("category")
        if image_id and new_category:
            if update_report_image_category(report_id, image_id, new_category):
                updated_any = True
    
    # 返回更新后的报告列表片段
    
    patient = get_object_or_404(PatientProfile, pk=patient_id)
    context = {"patient": patient}
    
    # 保持 active_tab 为 reports
    context["active_tab"] = "reports"
    
    template_name = handle_reports_history_section(request, context)
    
    response = render(request, template_name, context)
    
    if updated_any:
        # 简单的 Toast 提示
        response["HX-Trigger"] = '{"show-toast": {"message": "保存成功", "type": "success"}}'
        
    return response
