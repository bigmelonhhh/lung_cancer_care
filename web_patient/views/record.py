from django.shortcuts import render, redirect
from django.urls import reverse
from django.http import HttpRequest, HttpResponse
from django.utils import timezone
from users.models import CustomUser
from health_data.services.health_metric import HealthMetricService
from health_data.models import MetricType
import os
from decimal import Decimal
from datetime import datetime
from django.contrib import messages
from users.decorators import auto_wechat_login, check_patient
import logging

@auto_wechat_login
@check_patient
def record_temperature(request: HttpRequest) -> HttpResponse:
    """
    【页面说明】体温录入页面 `/p/record/temperature/`
    【功能逻辑】
    1. 接收 openid 参数标识用户。
    2. 提交按钮（前端校验）。
    """
    patient = request.patient
    
    patient_id = patient.id or None
        
    # 处理 POST 请求提交数据
    if request.method == "POST":
        weight_val = request.POST.get('temperature')
        record_time = request.POST.get('record_time')
        
        if weight_val and patient_id:
            try:
                record_time_str = record_time.replace('T', ' ')
                if len(record_time_str.split(':')) == 2:
                    record_time_str += ':00'
                record_time = datetime.strptime(record_time_str, '%Y-%m-%d %H:%M:%S')
                HealthMetricService.save_manual_metric(
                    patient_id=int(patient_id),
                    metric_type=MetricType.BODY_TEMPERATURE,
                    value_main=Decimal(weight_val),
                    measured_at=record_time  
                )
                logging.info(f"体温数据保存成功: patient_id={patient_id}, weight={weight_val}")
                next_url = request.GET.get('next') or request.POST.get('next')
                messages.success(request, "提交成功！")
                if next_url:
                    return redirect(next_url)
                redirect_url = reverse("web_patient:patient_home")
                return redirect(f"{redirect_url}?temperature=true&patient_id={patient_id}")
            except Exception as e:
                logging.info(f"保存体重数据失败: {e}")
                return redirect(request.path_info)
        
    context = {
        "default_time": timezone.now(),
        "patient_id": patient_id,
        "now_obj": timezone.now() 
    }
    return render(request, "web_patient/record_temperature.html", context)
@auto_wechat_login
@check_patient
def record_bp(request: HttpRequest) -> HttpResponse:
    """
    【页面说明】血压心率录入页面 `/p/record/bp/`
    【功能逻辑】
    1. 接收 openid 参数标识用户。
    2. 显示当前时间作为默认测量时间。
    3. 提供收缩压、舒张压、心率输入框。
    4. 提交按钮（前端校验）。
    """
    # 优先从 GET 参数获取 patient_id
    patient = request.patient
    patient_id = patient.id or None
    
    # 处理 POST 请求提交数据
    if request.method == "POST":
        ssy_val = request.POST.get('ssy')
        szy_val = request.POST.get('szy')
        heart_val = request.POST.get('heart')
        record_time = request.POST.get('record_time')
        
        if ssy_val and szy_val and heart_val and patient_id:
            try:
                record_time_str = record_time.replace('T', ' ')
                if len(record_time_str.split(':')) == 2:
                    record_time_str += ':00'
                # 解析为datetime对象
                record_time = datetime.strptime(record_time_str, '%Y-%m-%d %H:%M:%S')
                HealthMetricService.save_manual_metric(
                    patient_id=int(patient_id),
                    metric_type=MetricType.BLOOD_PRESSURE,
                    value_main=Decimal(ssy_val),
                    value_sub=Decimal(szy_val),
                    measured_at=record_time  
                )
                HealthMetricService.save_manual_metric(
                    patient_id=int(patient_id),
                    metric_type=MetricType.HEART_RATE,
                    value_main=Decimal(heart_val),
                    measured_at=record_time  
                )
                logging.info(f"血氧数据保存成功: patient_id={patient_id}")
                next_url = request.GET.get('next') or request.POST.get('next')
                messages.success(request, "提交成功！")
                if next_url:
                    return redirect(next_url)
                
                # 显式跳转并带参数，确保首页回显
                redirect_url = reverse("web_patient:patient_home")
                return redirect(f"{redirect_url}?bp_hr=true&patient_id={patient_id}")
            except Exception as e:
                logging.info(f"保存体重数据失败: {e}")
                return redirect(request.path_info)
        
    context = {
        "default_time": timezone.now(),
        "patient_id": patient_id,
         "now_obj": timezone.now() 
    }
    return render(request, "web_patient/record_bp.html", context)

@auto_wechat_login
@check_patient
def record_spo2(request: HttpRequest) -> HttpResponse:
    """
    【页面说明】血氧饱和度录入页面 `/p/record/spo2/`
    【功能逻辑】
    1. 接收 openid 参数标识用户。
    2. 显示当前时间作为默认测量时间。
    3. 提供血氧饱和度输入框。
    4. 提交按钮（前端校验）。
    """
    patient = request.patient
    patient_id = patient.id or None
        
        
    # 处理 POST 请求提交数据
    if request.method == "POST":
        weight_val = request.POST.get('spo2')
        record_time = request.POST.get('record_time')
        
        if weight_val and patient_id:
            try:
                # 调用 Service 保存数据
                record_time_str = record_time.replace('T', ' ')
                if len(record_time_str.split(':')) == 2:
                    record_time_str += ':00'
                record_time = datetime.strptime(record_time_str, '%Y-%m-%d %H:%M:%S')
                HealthMetricService.save_manual_metric(
                    patient_id=int(patient_id),
                    metric_type=MetricType.BLOOD_OXYGEN,
                    value_main=Decimal(weight_val),
                    measured_at=record_time  
                )
                logging.info(f"血氧数据保存成功: patient_id={patient_id}, weight={weight_val}")
                next_url = request.GET.get('next') or request.POST.get('next')
                messages.success(request, "提交成功！")
                if next_url:
                    return redirect(next_url)
                
                # 显式跳转并带参数，确保首页回显
                redirect_url = reverse("web_patient:patient_home")
                return redirect(f"{redirect_url}?spo2=true&patient_id={patient_id}")
            except Exception as e:
                return redirect(request.path_info)
        
  
    context = {
        "default_time": timezone.now(),
        "patient_id": patient_id,
         "now_obj": timezone.now() 
    }
    return render(request, "web_patient/record_spo2.html", context)

@auto_wechat_login
@check_patient
def record_weight(request: HttpRequest) -> HttpResponse:
    """
    【页面说明】体重录入页面 `/p/record/weight/`
    【功能逻辑】
    1. 接收 openid 参数标识用户。
    2. 显示当前时间作为默认测量时间。
    3. 提供体重输入框。
    4. 提交按钮（前端校验）。
    """
    patient = request.patient
    patient_id = patient.id or None
        
    # 处理 POST 请求提交数据
    if request.method == "POST":
        weight_val = request.POST.get('weight')
        record_time = request.POST.get('record_time')
        
        if weight_val and patient_id:
            try:
                 # 替换T为空格，补全秒数
                record_time_str = record_time.replace('T', ' ')
                if len(record_time_str.split(':')) == 2:
                    record_time_str += ':00'
                
                # 1. 先解析为无时区的datetime（naive）
                record_time_naive = datetime.strptime(record_time_str, '%Y-%m-%d %H:%M:%S')
                # 2. 转换为带时区的datetime（使用Django配置的TIME_ZONE，如Asia/Shanghai）
                record_time = timezone.make_aware(record_time_naive)
                HealthMetricService.save_manual_metric(
                    patient_id=int(patient_id),
                    metric_type=MetricType.WEIGHT,
                    value_main=Decimal(weight_val),
                    measured_at=record_time  # Service 内部会处理时间格式
                )
                logging.info(f"体重数据保存成功: patient_id={patient_id}, weight={weight_val}")
                next_url = request.GET.get('next') or request.POST.get('next')
                messages.success(request, "提交成功！")
                if next_url:
                    return redirect(next_url)
                
                # 显式跳转并带参数，确保首页回显
                redirect_url = reverse("web_patient:patient_home")
                return redirect(f"{redirect_url}?weight=true&patient_id={patient_id}")
            except Exception as e:
                messages.error(request, f"提交失败：{str(e)}")
                return redirect(request.path_info)
                
        
    context = {
        "default_time": timezone.now(),
        "patient_id": patient_id,
        "now_obj": timezone.now() 
    }
    return render(request, "web_patient/record_weight.html", context)

@auto_wechat_login
@check_patient
def record_breath(request: HttpRequest) -> HttpResponse:
    """
    【页面说明】呼吸情况自测页面 `/p/record/breath/`
    【功能逻辑】
    1. 接收 openid 参数标识用户。
    2. 显示当前时间作为默认测量时间。
    3. 提供呼吸情况多选列表（数据由后端传入）。
    4. 提交按钮。
    """
    patient = request.patient
    patient_id = patient.id or None
        
    # 获取当前时间，格式化为 YYYY/MM/DD HH:mm
    now = timezone.now()
    default_time = now.strftime("%Y/%m/%d %H:%M")

    # 呼吸情况选项数据
    breath_options = [
        {"value": "0", "label": "(0) 整体顺畅，仅剧烈运动气促"},
        {"value": "1", "label": "(1) 快走或上坡气促"},
        {"value": "2", "label": "(2) 与同龄人同走需停下"},
        {"value": "3", "label": "(3) 走100米或几分钟即停"},
        {"value": "4", "label": "(4) 静息或穿衣即气促"},
    ]

    context = {
        "default_time": default_time,
        "patient_id": patient_id,
        "breath_options": breath_options
    }
    
    return render(request, "web_patient/record_breath.html", context)

@auto_wechat_login
@check_patient
def record_sputum(request: HttpRequest) -> HttpResponse:
    """
    【页面说明】咳嗽与痰色情况自测页面 `/p/record/sputum/`
    【功能逻辑】
    1. 接收 openid 参数标识用户。
    2. 显示当前时间作为默认测量时间。
    3. 提供咳嗽情况（多选）和痰色情况（单选网格）。
    4. 提交按钮。
    """
    patient = request.patient
    patient_id = patient.id or None
        
    # 获取当前时间，格式化为 YYYY/MM/DD HH:mm
    now = timezone.now()
    default_time = now.strftime("%Y/%m/%d %H:%M")

    # 咳嗽情况选项数据（多选）
    cough_options = [
        {"value": "0", "label": "(0) 今日无咳嗽"},
        {"value": "1", "label": "(1) 轻度/偶发"},
        {"value": "2", "label": "(2) 多次影响活动或夜间休息"},
        {"value": "3", "label": "(3) 持续或严重影响说话/睡眠"},
    ]

    # 痰色情况选项数据（单选网格）
    # color_class 用于前端显示颜色条或图标颜色
    sputum_colors = [
        {"value": "0", "label": "(0)无痰", "desc": "无痰/透明", "color_class": "bg-gray-100","color_hex": ""},
        {"value": "1", "label": "(1)白色", "desc": "较黏/浑白", "color_class": "bg-white border-gray-200","color_hex": "#FFFFFF"},
        {"value": "2", "label": "(2)黄色", "desc": "发黄/黏稠", "color_class": "bg-yellow-100 border-yellow-200","color_hex": "#FACC15"},
        {"value": "3", "label": "(3)绿色", "desc": "发绿/黏稠", "color_class": "bg-green-100 border-green-200","color_hex": "#A5B30B"},
        {"value": "4", "label": "(4)棕色", "desc": "铁锈色/黏稠", "color_class": "bg-amber-100 border-amber-200","color_hex": "#A56415"},
        {"value": "5", "label": "(5)红色", "desc": "有血丝或血块", "color_class": "bg-red-100 border-red-200","color_hex": "#EF4444"},
    ]

    context = {
        "default_time": default_time,
        "patient_id": patient_id,
        "cough_options": cough_options,
        "sputum_colors": sputum_colors
    }
    
    return render(request, "web_patient/record_sputum.html", context)

@auto_wechat_login
@check_patient
def record_pain(request: HttpRequest) -> HttpResponse:
    """
    【页面说明】疼痛情况记录页面 `/p/record/pain/`
    【功能逻辑】
    1. 接收 openid 参数标识用户。
    2. 显示当前时间作为默认测量时间。
    3. 提供疼痛情况列表（数据由后端传入）。
    4. 实现联动逻辑：选中非第一项时，展示程度单选。
    5. 提交按钮。
    """
    patient = request.patient
    patient_id = patient.id or None
        
    # 获取当前时间，格式化为 YYYY/MM/DD HH:mm
    now = timezone.now()
    default_time = now.strftime("%Y/%m/%d %H:%M")

    # 疼痛部位选项
    pain_locations = [
        {"value": "0", "label": "今日无疼痛情况", "is_none": True},
        {"value": "1", "label": "术口/胸膛/肋间"},
        {"value": "2", "label": "肩峰/肩背/肩胛"},
        {"value": "3", "label": "肋骨/脊柱/骨盆/四肢"},
        {"value": "4", "label": "头痛"},
    ]

    # 疼痛程度选项
    pain_levels = [
        {
            "level": "mild",
            "label": "轻度：",
            "desc": "能做家务/正常活动，睡眠基本不受影响",
            "options": [
                {"value": "1", "label": "1分"},
                {"value": "2", "label": "2分"},
                {"value": "3", "label": "3分"},
            ]
        },
        {
            "level": "moderate",
            "label": "中度：",
            "desc": "活动或睡眠受影响，需要（或增加）止痛药",
            "options": [
                {"value": "4", "label": "4分"},
                {"value": "5", "label": "5分"},
                {"value": "6", "label": "6分"},
            ]
        },
        {
            "level": "severe",
            "label": "重度：",
            "desc": "明显疼痛或无法入眠，需要立即处理/尽快就医",
            "options": [
                {"value": "7", "label": "7分"},
                {"value": "8", "label": "8分"},
                {"value": "9", "label": "9分"},
                {"value": "10", "label": "10分"},
            ]
        },
    ]

    context = {
        "default_time": default_time,
        "patient_id": patient_id,
        "pain_locations": pain_locations,
        "pain_levels": pain_levels
    }
    
    return render(request, "web_patient/record_pain.html", context)
@auto_wechat_login
@check_patient
def health_records(request: HttpRequest) -> HttpResponse:
    """
    【页面说明】健康档案页面 `/p/health/records/`
    【功能逻辑】
    1. 展示各项健康指标的记录统计（记录次数、异常次数）。
    2. 支持空状态展示。
    """
    patient = request.patient
    patient_id = patient.id or None
    

    # TODO 待联调健康档案列表接口 模拟数据：健康指标记录
    # 实际开发中应从数据库统计
    health_stats = [
        {"type": "temperature", "title": "体温", "count": 0, "abnormal": 0, "icon": "temperature"},
        {"type": "breath", "title": "呼吸", "count": 0, "abnormal": 0, "icon": "breath"},
        {"type": "sputum", "title": "咳嗽/痰色", "count": 0, "abnormal": 0, "icon": "sputum"},
        {"type": "pain", "title": "疼痛", "count": 0, "abnormal": 0, "icon": "pain"},
        {"type": "weight", "title": "体重", "count": 0, "abnormal": 0, "icon": "weight"},
        {"type": "spo2", "title": "血氧", "count": 0, "abnormal": 0, "icon": "spo2"},
        {"type": "bp", "title": "血压", "count": 0, "abnormal": 0, "icon": "bp"},
        {"type": "heart", "title": "心率", "count": 0, "abnormal": 0, "icon": "heart"},
    ]
    
    # 模拟空数据测试
    # health_stats = []

    context = {
        "patient_id": patient_id,
        "health_stats": health_stats
    }

    return render(request, "web_patient/health_records.html", context)
@auto_wechat_login
@check_patient
def record_checkup(request: HttpRequest) -> HttpResponse:
    """
    【页面说明】复查上报页面 `/p/record/checkup/`
    【功能逻辑】
    1. 接收 openid 参数标识用户。
    2. 展示本次复查日期和复查项目。
    3. 支持图片上传（前端模拟预览）。
    4. 提交按钮（前端校验每个项目至少有一张图片）。
    """
    
    patient = request.patient
    patient_id = patient.id or None
        
    # TODO 待联调复查上报接口 模拟数据
    checkup_date = "2025-12-29"
    checkup_items = [
        {"id": 1, "name": "血常规"},
        {"id": 2, "name": "血生化"},
        {"id": 3, "name": "骨扫描"},
    ]

    context = {
        "patient_id": patient_id,
        "checkup_date": checkup_date,
        "checkup_items": checkup_items
    }
    
    return render(request, "web_patient/record_checkup.html", context)

@auto_wechat_login
@check_patient
def health_record_detail(request: HttpRequest) -> HttpResponse:
    """
    【页面说明】健康档案详情页 `/p/health/record/detail/`
    【功能逻辑】
    1. 接收 type 和 title 参数。
    2. 生成对应类型的模拟历史数据。
    3. 支持按月份筛选（目前仅前端展示）。
    """
    record_type = request.GET.get('type')
    title = request.GET.get('title', '历史记录')
    
    patient = request.patient
    patient_id = patient.id or None

    
    # 获取当前月份（YYYY-MM）
    current_month = request.GET.get('month', datetime.now().strftime("%Y-%m"))
    
    # 计算查询的时间范围
    try:
        start_date = datetime.strptime(current_month, "%Y-%m")
        # 下个月的第一天
        if start_date.month == 12:
            end_date = start_date.replace(year=start_date.year + 1, month=1)
        else:
            end_date = start_date.replace(month=start_date.month + 1)
    except ValueError:
        start_date = datetime.now().replace(day=1)
        if start_date.month == 12:
            end_date = start_date.replace(year=start_date.year + 1, month=1)
        else:
            end_date = start_date.replace(month=start_date.month + 1)
        current_month = start_date.strftime("%Y-%m")

    # 分页参数
    page = int(request.GET.get('page', 1))
    limit = int(request.GET.get('limit', 30))

    # 调用 Service 获取数据
    records = []
    total_count = 0
    has_more = False
    
    if patient_id and record_type:
        try:
            # 映射前端 type 到后端 MetricType
            metric_type_map = {
                "temperature": MetricType.BODY_TEMPERATURE,
                "bp": MetricType.BLOOD_PRESSURE,
                "spo2": MetricType.BLOOD_OXYGEN,
                "weight": MetricType.WEIGHT,
                # "breath": MetricType.DYSPNEA, # 假设呼吸对应 dyspnea
                # "sputum": MetricType.SPUTUM_COLOR, # 假设痰色对应 sputum_color
                "step": MetricType.STEPS,
                # "pain": MetricType.PAIN_INCISION, # 暂定
                "heart": MetricType.HEART_RATE,
            }
            
            db_metric_type = metric_type_map.get(record_type)
            
            if db_metric_type:
                page_obj = HealthMetricService.query_metrics_by_type(
                    patient_id=int(patient_id),
                    metric_type=db_metric_type,
                    page=page,
                    page_size=limit,
                    start_date=start_date,
                    end_date=end_date
                )

                total_count = page_obj.paginator.count
                raw_list = page_obj.object_list
                has_more = page < page_obj.paginator.num_pages
                weekday_map = {0: "星期一", 1: "星期二", 2: "星期三", 3: "星期四", 4: "星期五", 5: "星期六", 6: "星期日"}
                for metric in raw_list:
                    # measured_at 是带时区的 datetime
                    dt = metric.measured_at.astimezone(timezone.get_current_timezone())
                    date_str = dt.strftime("%Y-%m-%d")
                    time_str = dt.strftime("%H:%M")
                    
                    # 构造 data_fields
                    data_fields = []
                    if record_type == 'temperature':
                        data_fields.append({"label": "体温", "value": metric.display_value, "is_large": True, "key": "temperature"})
                    elif record_type == 'weight':
                        data_fields.append({"label": "体重", "value": metric.display_value, "is_large": True, "key": "weight"})
                    elif record_type == 'spo2':
                        data_fields.append({"label": "血氧", "value": metric.display_value, "is_large": True, "key": "spo2"})
                    elif record_type == 'bp':
                        data_fields = [
                            {"label": "收缩压", "value": str(int(metric.value_main)), "is_large": True, "key": "ssy"},
                            {"label": "舒张压", "value": str(int(metric.value_sub or 0)), "is_large": True, "key": "szy"},
                            # {"label": "心率", "value": "80", "is_large": True, "key": "heart"} # 暂无心率关联
                        ]
                    # ... 其他类型处理
                    else:
                         data_fields.append({"label": title, "value": metric.display_value, "is_large": True, "key": "common"})

                    records.append({
                        "id": metric.id,
                        "date": date_str,
                        "weekday": weekday_map[dt.weekday()],
                        "time": time_str,
                        "source": metric.source,
                        "source_display": "手动填写" if metric.source == 'manual' else "设备上传",
                        "is_manual": metric.source == 'manual',
                        "can_edit": metric.source == 'manual' and dt.date() == datetime.now().date(),
                        "data": data_fields
                    })
                    
        except Exception as e:
            logging.info(f"查询详情失败: {e}")
            return redirect(request.path_info)

    # 如果是 AJAX 请求，返回 JSON
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        from django.http import JsonResponse
        return JsonResponse({
            "records": records,
            "has_more": has_more,
            "next_page": page + 1 if has_more else None
        })

    context = {
        "record_type": record_type,
        "title": title,
        "records": records,
        "current_month": current_month,
        "patient_id": patient_id,
        "has_more": has_more,
        "next_page": page + 1 if has_more else None
    }
    
    return render(request, "web_patient/health_record_detail.html", context)
