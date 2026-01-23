from django.shortcuts import render, redirect
from django.urls import reverse
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone
from users.models import CustomUser
from health_data.services.health_metric import HealthMetricService
from health_data.models import MetricType
from core.models import QuestionnaireCode
from patient_alerts.services.todo_list import TodoListService
from core.service.tasks import get_daily_plan_summary
import os
from decimal import Decimal
from datetime import datetime
from django.contrib import messages
from users.decorators import auto_wechat_login, check_patient
import logging


@auto_wechat_login
@check_patient
def query_last_metric(request: HttpRequest) -> JsonResponse:
    """
    API: 查询今日最新健康指标状态
    """
    patient = request.patient
    if not patient:
        return JsonResponse({"error": "No patient info"}, status=400)
    
    # 1. 获取今日计划摘要 (包含完成状态)
    summary_list = get_daily_plan_summary(patient)
    
    # 2. 获取最新指标数据 (用于显示数值)
    last_metrics = HealthMetricService.query_last_metric(patient.id)
    
    # 3. 组装返回数据
    # 我们需要返回一个列表，或者以 type 为 key 的字典
    # 前端需要根据 type 更新 subtitle 和 status
    
    result = {}
    
    # 辅助函数：判断数据是否为今日
    def is_today(metric_info):
        if not metric_info or 'measured_at' not in metric_info:
            return False
        utc_time = metric_info['measured_at']
        local_time = timezone.localtime(utc_time)
        return local_time.date() == timezone.localdate()

    # 处理计划列表
    for item in summary_list:
        title = item.get("title", "")
        status_val = item.get("status", 0) # 0=pending, 1=completed
        
        # 映射 type
        # 简单映射逻辑，需与 patient_home 保持一致
        plan_type = "unknown"
        if "用药" in title: plan_type = "medication"
        elif "体温" in title: plan_type = "temperature"
        elif "血压" in title or "心率" in title: plan_type = "bp_hr"
        elif "血氧" in title: plan_type = "spo2"
        elif "体重" in title: plan_type = "weight"
        elif "随访" in title or "问卷" in title: plan_type = "followup"
        elif "复查" in title: plan_type = "checkup"
        
        if plan_type == "unknown": continue
        
        # Determine default subtitle based on type (Logic from home.py)
        default_subtitle = ""
        if plan_type == "medication":
            default_subtitle = "您今天还未服药" if status_val == 0 else "今日已服药"
        elif plan_type == "temperature":
            default_subtitle = "请记录今日体温"
        elif plan_type == "bp_hr":
            default_subtitle = "请记录今日血压心率情况"
        elif plan_type == "spo2":
            default_subtitle = "请记录今日血氧饱和度"
        elif plan_type == "weight":
            default_subtitle = "请记录今日体重"
        elif plan_type == "followup":
            default_subtitle = "请及时完成您的随访任务" if status_val == 0 else "今日已完成"
        elif plan_type == "checkup":
            default_subtitle = "请及时完成您的复查任务" if status_val == 0 else "今日已完成"

        plan_data = {
            "type": plan_type,
            "status": "completed" if status_val == 1 else "pending",
            "subtitle": item.get("subtitle") or default_subtitle
        }
        
        # 获取数值展示，仅当状态为 completed 时更新 subtitle
        if status_val == 1:
            if plan_type == "temperature" and MetricType.BODY_TEMPERATURE in last_metrics:
                info = last_metrics[MetricType.BODY_TEMPERATURE]
                if is_today(info):
                    plan_data["subtitle"] = f"今日已记录：{info['value_display']}"
            
            elif plan_type == "bp_hr":
                # 血压心率特殊处理
                bp_info = last_metrics.get(MetricType.BLOOD_PRESSURE)
                hr_info = last_metrics.get(MetricType.HEART_RATE)
                if bp_info and is_today(bp_info):
                    bp_str = bp_info['value_display']
                    hr_str = hr_info['value_display'] if (hr_info and is_today(hr_info)) else "--"
                    plan_data["subtitle"] = f"今日已记录：血压{bp_str}mmHg，心率{hr_str}"
            
            elif plan_type == "spo2" and MetricType.BLOOD_OXYGEN in last_metrics:
                info = last_metrics[MetricType.BLOOD_OXYGEN]
                if is_today(info):
                    plan_data["subtitle"] = f"今日已记录：{info['value_display']}"
                    
            elif plan_type == "weight" and MetricType.WEIGHT in last_metrics:
                info = last_metrics[MetricType.WEIGHT]
                if is_today(info):
                    plan_data["subtitle"] = f"今日已记录：{info['value_display']}"
            
            elif plan_type == "medication":
                 plan_data["subtitle"] = "今日已服药"

            elif plan_type == "followup":
                 plan_data["subtitle"] = "今日已完成"
                     
            elif plan_type == "checkup":
                 plan_data["subtitle"] = "今日已完成"

        result[plan_type] = plan_data

    return JsonResponse({"success": True, "plans": result})


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
        weight_val = request.POST.get("temperature")
        record_time = request.POST.get("record_time")

        if weight_val and patient_id:
            try:
                record_time_str = record_time.replace("T", " ")
                if len(record_time_str.split(":")) == 2:
                    record_time_str += ":00"
                # 1. 解析 naive datetime
                record_time_naive = datetime.strptime(record_time_str, "%Y-%m-%d %H:%M:%S")
                # 2. 转换为 aware datetime
                record_time = timezone.make_aware(record_time_naive)
                
                HealthMetricService.save_manual_metric(
                    patient_id=int(patient_id),
                    metric_type=MetricType.BODY_TEMPERATURE,
                    value_main=Decimal(weight_val),
                    measured_at=record_time,
                )
                logging.info(
                    f"体温数据保存成功: patient_id={patient_id}, weight={weight_val}"
                )
                
                # AJAX 请求返回 JSON
                if request.headers.get("x-requested-with") == "XMLHttpRequest":
                    return JsonResponse({
                        "status": "success",
                        "redirect_url": "",
                        "metric_data": {
                            "temperature": {
                                "value": weight_val,
                                "status": "completed"
                            }
                        }
                    })

                next_url = request.GET.get("next") or request.POST.get("next")
                if next_url:
                    return redirect(next_url)
                
                # 移除强制跳转首页逻辑，改为刷新当前页并提示成功
                messages.success(request, "体温记录成功")
                return redirect(request.path)
            except Exception as e:
                logging.info(f"保存体重数据失败: {e}")
                return redirect(request.path_info)

    context = {
        "default_time": timezone.now(),
        "patient_id": patient_id,
        "now_obj": timezone.now(),
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
        ssy_val = request.POST.get("ssy")
        szy_val = request.POST.get("szy")
        heart_val = request.POST.get("heart")
        record_time = request.POST.get("record_time")

        if ssy_val and szy_val and heart_val and patient_id:
            try:
                record_time_str = record_time.replace("T", " ")
                if len(record_time_str.split(":")) == 2:
                    record_time_str += ":00"
                # 1. 解析 naive datetime
                record_time_naive = datetime.strptime(record_time_str, "%Y-%m-%d %H:%M:%S")
                # 2. 转换为 aware datetime
                record_time = timezone.make_aware(record_time_naive)

                HealthMetricService.save_manual_metric(
                    patient_id=int(patient_id),
                    metric_type=MetricType.BLOOD_PRESSURE,
                    value_main=Decimal(ssy_val),
                    value_sub=Decimal(szy_val),
                    measured_at=record_time,
                )
                HealthMetricService.save_manual_metric(
                    patient_id=int(patient_id),
                    metric_type=MetricType.HEART_RATE,
                    value_main=Decimal(heart_val),
                    measured_at=record_time,
                )
                logging.info(f"血氧数据保存成功: patient_id={patient_id}")
                
                # AJAX 请求返回 JSON
                if request.headers.get("x-requested-with") == "XMLHttpRequest":
                    return JsonResponse({
                        "status": "success",
                        "redirect_url": "",
                        "metric_data": {
                            "bp_hr": {
                                "ssy": ssy_val,
                                "szy": szy_val,
                                "heart": heart_val,
                                "status": "completed"
                            }
                        }
                    })

                next_url = request.GET.get("next") or request.POST.get("next")
                if next_url:
                    return redirect(next_url)

                # 移除强制跳转首页逻辑，改为刷新当前页并提示成功
                messages.success(request, "血压心率记录成功")
                return redirect(request.path)
            except Exception as e:
                logging.info(f"保存体重数据失败: {e}")
                return redirect(request.path_info)

    context = {
        "default_time": timezone.now(),
        "patient_id": patient_id,
        "now_obj": timezone.now(),
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
        weight_val = request.POST.get("spo2")
        record_time = request.POST.get("record_time")

        if weight_val and patient_id:
            try:
                # 调用 Service 保存数据
                record_time_str = record_time.replace("T", " ")
                if len(record_time_str.split(":")) == 2:
                    record_time_str += ":00"
                # 1. 解析 naive datetime
                record_time_naive = datetime.strptime(record_time_str, "%Y-%m-%d %H:%M:%S")
                # 2. 转换为 aware datetime
                record_time = timezone.make_aware(record_time_naive)

                HealthMetricService.save_manual_metric(
                    patient_id=int(patient_id),
                    metric_type=MetricType.BLOOD_OXYGEN,
                    value_main=Decimal(weight_val),
                    measured_at=record_time,
                )
                logging.info(
                    f"血氧数据保存成功: patient_id={patient_id}, weight={weight_val}"
                )

                # AJAX 请求返回 JSON
                if request.headers.get("x-requested-with") == "XMLHttpRequest":
                    return JsonResponse({
                        "status": "success",
                        "redirect_url": "",
                        "metric_data": {
                            "spo2": {
                                "value": weight_val,
                                "status": "completed"
                            }
                        }
                    })

                next_url = request.GET.get("next") or request.POST.get("next")
                if next_url:
                    return redirect(next_url)

                # 移除强制跳转首页逻辑，改为刷新当前页并提示成功
                messages.success(request, "血氧记录成功")
                return redirect(request.path)
            except Exception as e:
                return redirect(request.path_info)

    context = {
        "default_time": timezone.now(),
        "patient_id": patient_id,
        "now_obj": timezone.now(),
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
        weight_val = request.POST.get("weight")
        record_time = request.POST.get("record_time")

        if weight_val and patient_id:
            try:
                # 替换T为空格，补全秒数
                record_time_str = record_time.replace("T", " ")
                if len(record_time_str.split(":")) == 2:
                    record_time_str += ":00"

                # 1. 先解析为无时区的datetime（naive）
                record_time_naive = datetime.strptime(
                    record_time_str, "%Y-%m-%d %H:%M:%S"
                )
                # 2. 转换为带时区的datetime（使用Django配置的TIME_ZONE，如Asia/Shanghai）
                record_time = timezone.make_aware(record_time_naive)
                HealthMetricService.save_manual_metric(
                    patient_id=int(patient_id),
                    metric_type=MetricType.WEIGHT,
                    value_main=Decimal(weight_val),
                    measured_at=record_time,  # Service 内部会处理时间格式
                )
                logging.info(
                    f"体重数据保存成功: patient_id={patient_id}, weight={weight_val}"
                )

                # AJAX 请求返回 JSON
                if request.headers.get("x-requested-with") == "XMLHttpRequest":
                    return JsonResponse({
                        "status": "success",
                        "redirect_url": "",
                        "metric_data": {
                            "weight": {
                                "value": weight_val,
                                "status": "completed"
                            }
                        }
                    })

                next_url = request.GET.get("next") or request.POST.get("next")
                if next_url:
                    return redirect(next_url)

                # 移除强制跳转首页逻辑，改为刷新当前页并提示成功
                messages.success(request, "体重记录成功")
                return redirect(request.path)
            except Exception as e:
                messages.error(request, f"提交失败：{str(e)}")
                return redirect(request.path_info)

    context = {
        "default_time": timezone.now(),
        "patient_id": patient_id,
        "now_obj": timezone.now(),
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
        "breath_options": breath_options,
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
        {
            "value": "0",
            "label": "(0)无痰",
            "desc": "无痰/透明",
            "color_class": "bg-gray-100",
            "color_hex": "",
        },
        {
            "value": "1",
            "label": "(1)白色",
            "desc": "较黏/浑白",
            "color_class": "bg-white border-gray-200",
            "color_hex": "#FFFFFF",
        },
        {
            "value": "2",
            "label": "(2)黄色",
            "desc": "发黄/黏稠",
            "color_class": "bg-yellow-100 border-yellow-200",
            "color_hex": "#FACC15",
        },
        {
            "value": "3",
            "label": "(3)绿色",
            "desc": "发绿/黏稠",
            "color_class": "bg-green-100 border-green-200",
            "color_hex": "#A5B30B",
        },
        {
            "value": "4",
            "label": "(4)棕色",
            "desc": "铁锈色/黏稠",
            "color_class": "bg-amber-100 border-amber-200",
            "color_hex": "#A56415",
        },
        {
            "value": "5",
            "label": "(5)红色",
            "desc": "有血丝或血块",
            "color_class": "bg-red-100 border-red-200",
            "color_hex": "#EF4444",
        },
    ]

    context = {
        "default_time": default_time,
        "patient_id": patient_id,
        "cough_options": cough_options,
        "sputum_colors": sputum_colors,
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
            ],
        },
        {
            "level": "moderate",
            "label": "中度：",
            "desc": "活动或睡眠受影响，需要（或增加）止痛药",
            "options": [
                {"value": "4", "label": "4分"},
                {"value": "5", "label": "5分"},
                {"value": "6", "label": "6分"},
            ],
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
            ],
        },
    ]

    context = {
        "default_time": default_time,
        "patient_id": patient_id,
        "pain_locations": pain_locations,
        "pain_levels": pain_levels,
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

    # 一般检测数据
    health_stats = [
        {
            "type": "medical",
            "title": "用药",
            "count": 0,
            "abnormal": 0,
            "icon": "medical",
        },
        {
            "type": "temperature",
            "title": "体温",
            "count": 0,
            "abnormal": 0,
            "icon": "temperature",
        },
        {"type": "spo2", "title": "血氧", "count": 0, "abnormal": 0, "icon": "spo2"},
        {"type": "bp", "title": "血压", "count": 0, "abnormal": 0, "icon": "bp"},
        {
            "type": "weight",
            "title": "体重",
            "count": 0,
            "abnormal": 0,
            "icon": "weight",
        },
        {"type": "heart", "title": "心率", "count": 0, "abnormal": 0, "icon": "heart"},
        {"type": "step", "title": "步数", "count": 0, "abnormal": 0, "icon": "step"},
    ]

    # 动态获取各项指标的总数
    if patient_id:
        # 定义异常统计的时间范围（从较早时间到现在，覆盖所有历史）
        start_date = datetime(2000, 1, 1).date()
        end_date = timezone.now().date()

        metric_type_map = {
            "medical": MetricType.USE_MEDICATED,
            "temperature": MetricType.BODY_TEMPERATURE,
            "spo2": MetricType.BLOOD_OXYGEN,
            "bp": MetricType.BLOOD_PRESSURE,
            "weight": MetricType.WEIGHT,
            "heart": MetricType.HEART_RATE,
            "step": MetricType.STEPS,
        }

        for item in health_stats:
            m_type = metric_type_map.get(item["type"])
            if m_type:
                try:
                    # 调用 Service 获取分页对象，从而获取总数
                    # page=1, page_size=1 最小化数据传输
                    page_obj = HealthMetricService.query_metrics_by_type(
                        patient_id=int(patient_id),
                        metric_type=m_type,
                        page=1,
                        page_size=1,
                    )
                    item["count"] = page_obj.paginator.count

                    # 获取异常次数
                    item["abnormal"] = TodoListService.count_abnormal_events(
                        patient=patient,
                        start_date=start_date,
                        end_date=end_date,
                        type=m_type,
                    )
                except Exception as e:
                    logging.error(f"查询健康指标统计失败 type={item['type']}: {e}")
                    # 保持默认值 0
    # 随访问卷
    health_survey_stats = [
        {
            "type": "physical",
            "title": "体能评估",
            "count": 0,
            "abnormal": 0,
            "icon": "physical",
        },
        {
            "type": "breath",
            "title": "呼吸评估",
            "count": 0,
            "abnormal": 0,
            "icon": "breath",
        },
        {
            "type": "cough",
            "title": "咳嗽与痰色评估",
            "count": 0,
            "abnormal": 0,
            "icon": "cough",
        },
        {
            "type": "appetite",
            "title": "食欲评估",
            "count": 0,
            "abnormal": 0,
            "icon": "appetite",
        },
        {
            "type": "pain",
            "title": "身体疼痛评估",
            "count": 0,
            "abnormal": 0,
            "icon": "pain",
        },
        {
            "type": "sleep",
            "title": "睡眠质量评估",
            "count": 0,
            "abnormal": 0,
            "icon": "sleep",
        },
        {
            "type": "psych",
            "title": "抑郁评估",
            "count": 0,
            "abnormal": 0,
            "icon": "psych",
        },
        {
            "type": "anxiety",
            "title": "焦虑评估",
            "count": 0,
            "abnormal": 0,
            "icon": "anxiety",
        },
    ]
    # 动态获取各项指标的总数
    if patient_id:
        # 复用上面定义的时间范围
        start_date = datetime(2000, 1, 1).date()
        end_date = timezone.now().date()

        metric_type_map_survey = {
            "physical": QuestionnaireCode.Q_PHYSICAL,
            "breath": QuestionnaireCode.Q_BREATH,
            "cough": QuestionnaireCode.Q_COUGH,
            "appetite": QuestionnaireCode.Q_APPETITE,
            "pain": QuestionnaireCode.Q_PAIN,
            "sleep": QuestionnaireCode.Q_SLEEP,
            "psych": QuestionnaireCode.Q_PSYCH,
            "anxiety": QuestionnaireCode.Q_ANXIETY,
        }

        for item in health_survey_stats:
            m_type = metric_type_map_survey.get(item["type"])
            if m_type:
                try:
                    # 调用 Service 获取分页对象，从而获取总数
                    # page=1, page_size=1 最小化数据传输
                    page_obj = HealthMetricService.query_metrics_by_type(
                        patient_id=int(patient_id),
                        metric_type=m_type,
                        page=1,
                        page_size=1,
                    )
                    item["count"] = page_obj.paginator.count

                    # 获取异常次数
                    item["abnormal"] = TodoListService.count_abnormal_events(
                        patient=patient,
                        start_date=start_date,
                        end_date=end_date,
                        type_code=m_type,
                    )
                except Exception as e:
                    logging.error(f"查询健康指标统计失败 type={item['type']}: {e}")
                    # 保持默认值 0

    context = {
        "patient_id": patient_id,
        "health_stats": health_stats,
        "health_survey_stats": health_survey_stats,
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
    from core.models import DailyTask
    from core.models.choices import PlanItemCategory, TaskStatus, ReportType
    from health_data.models.report_upload import ReportUpload, ReportImage, UploadSource, UploaderRole
    from health_data.services.report_service import ReportUploadService
    from core.models.checkup import CheckupLibrary
    from django.core.files.storage import default_storage
    from django.core.files.base import ContentFile
    import uuid

    from django.db import transaction

    patient = request.patient
    patient_id = patient.id or None
    today = timezone.now().date()

    # 查询今日复查任务
    tasks = DailyTask.objects.filter(
        patient=patient,
        task_date=today,
        task_type=PlanItemCategory.CHECKUP
    )

    if request.method == "POST":
        try:
            with transaction.atomic():
                # 校验：是否所有展示的任务都上传了图片
                # 这里我们只检查 PENDING 状态的任务，或者页面上展示的任务
                # 假设页面展示所有今日任务
                
                uploaded_tasks_count = 0
                
                for task in tasks:
                    files = request.FILES.getlist(f'images_{task.id}')
                    if not files and task.status == TaskStatus.PENDING:
                        # 如果是待完成任务且没有上传图片，返回错误
                        # 注意：前端应该已经做过校验，这里是双重保障
                        # 也可以选择忽略未上传的任务，只处理上传了的
                        continue
    
                    if files:
                        # 预先筛选有效文件
                        valid_files = []
                        for f in files:
                            if f.size > 10 * 1024 * 1024:
                                logging.warning(f"File {f.name} too large: {f.size}")
                                continue
                            ext = os.path.splitext(f.name)[1].lower()
                            if ext in ['.jpg', '.jpeg', '.png']:
                                valid_files.append(f)
                            else:
                                logging.warning(f"Invalid file type: {f.name}")
                        
                        if not valid_files:
                            logging.info(f"No valid files for task {task.id}")
                            continue

                        # 尝试匹配 CheckupLibrary
                        # 优先从 interaction_payload 获取 checkup_code 或 checkup_id
                        checkup_item = None
                        checkup_id = task.interaction_payload.get('checkup_id')
                        if checkup_id:
                            checkup_item = CheckupLibrary.objects.filter(id=checkup_id).first()
                        
                        # 降级：通过标题匹配
                        if not checkup_item:
                             checkup_item = CheckupLibrary.objects.filter(name=task.title).first()

                        # 准备图片数据列表
                        image_payloads = []
                        for f in valid_files:
                            # 保存文件
                            file_path = f"checkup_reports/{patient.id}/{today}/{uuid.uuid4()}{os.path.splitext(f.name)[1].lower()}"
                            saved_path = default_storage.save(file_path, ContentFile(f.read()))
                            
                            # 获取 URL
                            # 如果 default_storage 是本地文件系统，url() 返回 /media/path
                            # 如果配置了 MEDIA_URL，通常没问题
                            # 为了保险，如果 image_url 是相对路径，我们可以考虑是否需要 request.build_absolute_uri
                            # 但 ReportImage.image_url 是 URLField，通常存储完整 URL 或绝对路径
                            image_url = default_storage.url(saved_path)
                            
                            # 确保 image_url 是可访问的。如果是相对路径且不是完整 URL，可能需要处理。
                            # 多数情况下，/media/... 是可以直接使用的。
                            # 假设 image_url 已经是 /media/... 或者是完整 URL (云存储)
                            
                            payload = {
                                "image_url": image_url,
                                "record_type": ReportImage.RecordType.CHECKUP,
                                "report_date": today
                            }
                            # Explicitly set checkup_item
                            if checkup_item:
                                payload["checkup_item"] = checkup_item
                            
                            image_payloads.append(payload)

                        # 调用 Service 统一创建记录
                        ReportUploadService.create_upload(
                            patient=patient,
                            images=image_payloads,
                            uploader=request.user,
                            upload_source=UploadSource.CHECKUP_PLAN,
                            uploader_role=UploaderRole.PATIENT,
                            related_task=task
                        )
                        
                        # 更新任务状态
                        task.mark_completed()
                        uploaded_tasks_count += 1
                
                if uploaded_tasks_count > 0:
                     # AJAX 请求返回 JSON
                    if request.headers.get("x-requested-with") == "XMLHttpRequest":
                        return JsonResponse({
                            "status": "success",
                            "redirect_url": reverse('web_patient:patient_home')
                        })
                    
                    messages.success(request, "复查报告上传成功")
                    return redirect('web_patient:patient_home')
                else:
                     if request.headers.get("x-requested-with") == "XMLHttpRequest":
                        return JsonResponse({"status": "error", "message": "未检测到有效的图片上传"}, status=400)
    
        except Exception as e:
            logging.error(f"复查上报失败: {e}", exc_info=True)
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"status": "error", "message": str(e)}, status=500)
            messages.error(request, "上传失败，请重试")
            return redirect(request.path)

    # 构造前端所需的数据结构
    checkup_items = []
    for task in tasks:
        # 获取该任务已上传的图片
        uploaded_images = []
        # 查找关联的 ReportUpload
        uploads = ReportUpload.objects.filter(related_task=task)
        for upload in uploads:
            images = ReportImage.objects.filter(upload=upload)
            for img in images:
                uploaded_images.append({
                    "id": img.id,
                    "url": img.image_url,
                    "date": img.report_date.strftime("%Y-%m-%d") if img.report_date else ""
                })

        checkup_items.append({
            "id": task.id,
            "name": task.title,
            "is_completed": task.status == TaskStatus.COMPLETED,
            "existing_images": uploaded_images
        })

    context = {
        "patient_id": patient_id,
        "checkup_date": today.strftime("%Y-%m-%d"),
        "checkup_items": checkup_items,
    }

    return render(request, "web_patient/record_checkup.html", context)


@auto_wechat_login
@check_patient
def delete_report_image(request: HttpRequest, image_id: int) -> JsonResponse:
    """
    删除复查图片接口
    POST /p/record/image/<id>/delete/
    """
    from health_data.models.report_upload import ReportImage
    
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Method not allowed"}, status=405)
        
    try:
        image = ReportImage.objects.get(id=image_id)
        
        # 权限校验：确保是当前患者的图片
        if image.upload.patient != request.patient:
            return JsonResponse({"status": "error", "message": "无权删除此图片"}, status=403)
            
        # 物理删除文件 (Optional, Django FileField usually handles this via signals or manual delete)
        if image.image_url:
             # 注意：image_url 可能是 URL 路径，需要转换为 storage path
             # 这里简单处理，依赖 storage backend
             pass

        # 删除数据库记录
        image.delete()
        
        logging.info(f"User {request.user.id} deleted ReportImage {image_id}")
        
        return JsonResponse({"status": "success"})
        
    except ReportImage.DoesNotExist:
        return JsonResponse({"status": "error", "message": "图片不存在"}, status=404)
    except Exception as e:
        logging.error(f"删除图片失败: {e}", exc_info=True)
        return JsonResponse({"status": "error", "message": "删除失败，请重试"}, status=500)


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
    record_type = request.GET.get("type")
    title = request.GET.get("title", "历史记录")

    patient = request.patient
    patient_id = patient.id or None

    # 获取当前月份（YYYY-MM）
    current_month = request.GET.get("month", datetime.now().strftime("%Y-%m"))

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

    tz = timezone.get_current_timezone()
    if timezone.is_naive(start_date):
        start_date = timezone.make_aware(start_date, tz)
    if timezone.is_naive(end_date):
        end_date = timezone.make_aware(end_date, tz)

    # 分页参数
    page = int(request.GET.get("page", 1))
    limit = int(request.GET.get("limit", 30))

    # 调用 Service 获取数据
    records = []
    total_count = 0
    has_more = False

    if patient_id and record_type:
        try:
            # 映射前端 type 到后端 MetricType
            metric_type_map = {
                "medical": MetricType.USE_MEDICATED,
                "temperature": MetricType.BODY_TEMPERATURE,
                "bp": MetricType.BLOOD_PRESSURE,
                "spo2": MetricType.BLOOD_OXYGEN,
                "weight": MetricType.WEIGHT,
                "step": MetricType.STEPS,
                "heart": MetricType.HEART_RATE,
                "physical": QuestionnaireCode.Q_PHYSICAL,
                "breath": QuestionnaireCode.Q_BREATH,
                "cough": QuestionnaireCode.Q_COUGH,
                "appetite": QuestionnaireCode.Q_APPETITE,
                "pain": QuestionnaireCode.Q_PAIN,
                "sleep": QuestionnaireCode.Q_SLEEP,
                "psych": QuestionnaireCode.Q_PSYCH,
                "anxiety": QuestionnaireCode.Q_ANXIETY,
            }

            db_metric_type = metric_type_map.get(record_type)

            if db_metric_type:
                page_obj = HealthMetricService.query_metrics_by_type(
                    patient_id=int(patient_id),
                    metric_type=db_metric_type,
                    page=page,
                    page_size=limit,
                    start_date=start_date,
                    end_date=end_date,
                )

                total_count = page_obj.paginator.count
                raw_list = page_obj.object_list
                has_more = page < page_obj.paginator.num_pages
                weekday_map = {
                    0: "星期一",
                    1: "星期二",
                    2: "星期三",
                    3: "星期四",
                    4: "星期五",
                    5: "星期六",
                    6: "星期日",
                }
                for metric in raw_list:
                    # measured_at 是带时区的 datetime
                    dt = metric.measured_at.astimezone(timezone.get_current_timezone())
                    date_str = dt.strftime("%Y-%m-%d")
                    time_str = dt.strftime("%H:%M")

                    # 构造 data_fields
                    data_fields = []
                    if record_type == "temperature":
                        data_fields.append(
                            {
                                "label": "体温",
                                "value": metric.display_value,
                                "is_large": True,
                                "key": "temperature",
                            }
                        )
                    elif record_type == "weight":
                        data_fields.append(
                            {
                                "label": "体重",
                                "value": metric.display_value,
                                "is_large": True,
                                "key": "weight",
                            }
                        )
                    elif record_type == "spo2":
                        data_fields.append(
                            {
                                "label": "血氧",
                                "value": metric.display_value,
                                "is_large": True,
                                "key": "spo2",
                            }
                        )
                    elif record_type == "bp":
                        data_fields = [
                            {
                                "label": "收缩压",
                                "value": str(int(metric.value_main)),
                                "is_large": True,
                                "key": "ssy",
                            },
                            {
                                "label": "舒张压",
                                "value": str(int(metric.value_sub or 0)),
                                "is_large": True,
                                "key": "szy",
                            },
                            # {"label": "心率", "value": "80", "is_large": True, "key": "heart"} # 暂无心率关联
                        ]
                    # ... 其他类型处理
                    else:
                        data_fields.append(
                            {
                                "label": title,
                                "value": metric.display_value,
                                "is_large": True,
                                "key": "common",
                            }
                        )

                    records.append(
                        {
                            "id": metric.id,
                            "date": date_str,
                            "weekday": weekday_map[dt.weekday()],
                            "time": time_str,
                            "source": metric.source,
                            "source_display": (
                                "手动填写" if metric.source == "manual" else "设备上传"
                            ),
                            "is_manual": metric.source == "manual",
                            "can_edit": metric.source == "manual"
                            and dt.date() == datetime.now().date(),
                            "data": data_fields,
                        }
                    )

        except Exception as e:
            logging.info(f"查询详情失败: {e}")
            return redirect(request.path_info)

    # 如果是 AJAX 请求，返回 JSON
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        from django.http import JsonResponse

        return JsonResponse(
            {
                "records": records,
                "has_more": has_more,
                "next_page": page + 1 if has_more else None,
            }
        )

    context = {
        "record_type": record_type,
        "title": title,
        "records": records,
        "current_month": current_month,
        "patient_id": patient_id,
        "has_more": has_more,
        "next_page": page + 1 if has_more else None,
    }

    return render(request, "web_patient/health_record_detail.html", context)
