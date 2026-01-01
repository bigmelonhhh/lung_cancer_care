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

# 全局变量存储模拟数据，实现内存级持久化
MOCK_REPORTS_DATA: List[Dict[str, Any]] = []

# TODO 1、待联调检查报告列表接口
# TODO 2、获取图片分类接口
# TODO 3、编辑接口-可以修改图片分类、报告解读内容
def _init_mock_data():
    """初始化模拟数据"""
    global MOCK_REPORTS_DATA
    if MOCK_REPORTS_DATA:
        return

    report_types = ["CT胸部平扫", "MRI头部扫描", "血常规", "肝功能", "肿瘤标志物"]
    statuses = ["已完成", "待审核", "已打印"]
    
    for i in range(15):
        # 随机生成图片数量 (1-6张)
        img_count = random.randint(1, 6)
        
        # 生成图片对象列表
        images = []
        for j in range(img_count):
            images.append({
                "id": f"{i}-{j}",  # 唯一标识
                "name": f"图片-{j+1}",
                "url": f"https://placehold.co/200x200?text=Report+{i}-{j}",
                "category": "其他"  # 默认分类
            })
        
        # 模拟报告解读内容
        interpretation = (
            f"这是关于报告 {i} 的解读内容。患者情况稳定，建议继续观察。影像学表现符合术后改变。" 
            if i % 3 != 0 else ""
        )
        
        # 模拟推送状态
        is_pushed = i % 2 == 0
        
        # 模拟日期（倒序排列）
        date_str = f"2025-11-{12-i if 12-i > 0 else 1:02d} 14:22"

        MOCK_REPORTS_DATA.append({
            "id": 1000 + i,
            "date": date_str,
            "images": images,
            "interpretation": interpretation,
            "is_pushed": is_pushed,
            "patient_info": {
                "name": "模拟患者",
                "age": random.randint(45, 75)
            },
            "report_type": random.choice(report_types),
            "status": random.choice(statuses)
        })

def get_mock_reports_data() -> List[Dict[str, Any]]:
    """
    获取检查报告历史记录模拟数据
    """
    _init_mock_data()
    return MOCK_REPORTS_DATA

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

def get_report_image_categories():
    """获取所有可用的图片分类"""
    return REPORT_IMAGE_CATEGORIES

def handle_reports_history_section(request: HttpRequest, context: dict) -> str:
    """
    处理检查报告历史记录板块
    """
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
        "image_categories": get_report_image_categories(),
    })
    return template_name

@login_required
@check_doctor_or_assistant
@require_POST
def patient_report_update(request: HttpRequest, patient_id: int, report_id: int) -> HttpResponse:
    """
    更新检查报告信息（包括图片分类）
    """
    import json

    # 解析 JSON 数据
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponse("无效的 JSON 数据", status=400)

    image_updates = data.get("image_updates", [])
    
    # 批量更新图片分类
    updated_any = False
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
