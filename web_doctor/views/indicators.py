import logging
from datetime import date, timedelta, datetime
from django.utils import timezone
from django.core.cache import cache
from core.models import TreatmentCycle, choices
from core.service.treatment_cycle import get_treatment_cycles
from core.service.tasks import get_adherence_metrics_batch
from health_data.services.health_metric import HealthMetricService
from health_data.models.health_metric import MetricType
from users.models import PatientProfile

logger = logging.getLogger(__name__)

def build_indicators_context(
    patient: PatientProfile,
    cycle_id: str | None = None,
    start_date_str: str | None = None,
    end_date_str: str | None = None,
    filter_type: str | None = None
) -> dict:
    """
    构建“患者指标”Tab 所需的上下文数据：
    - 查询近30天数据
    - 获取疗程列表
    """
    today = timezone.localdate()
    
    # 默认值：近30天
    start_date = today - timedelta(days=29)
    end_date = today
    
    is_default_view = True
    
    # 根据 filter_type 决定优先级
    if filter_type == 'cycle':
        # 即使 cycle_id 为空（全部疗程），也视为 cycle 模式，但使用默认日期
        if cycle_id:
            try:
                cycle = TreatmentCycle.objects.get(pk=cycle_id, patient=patient)
                start_date = cycle.start_date
                end_date = cycle.end_date if cycle.end_date else today
                is_default_view = False
            except (TreatmentCycle.DoesNotExist, ValueError):
                pass
        else:
             # cycle_id 为空 -> "全部疗程" -> 默认30天，但需要保持 filter_type='cycle'
             # is_default_view = True (UI上可能需要根据 filter_type 判断)
             pass
             
    elif filter_type == 'date':
        if start_date_str and end_date_str:
            try:
                start_date = date.fromisoformat(start_date_str)
                end_date = date.fromisoformat(end_date_str)
                is_default_view = False
            except ValueError:
                pass
    
    # 兼容旧逻辑（如果 filter_type 未传，尝试推断）
    elif not filter_type:
        # 1. 优先使用自定义日期范围
        if start_date_str and end_date_str:
            try:
                start_date = date.fromisoformat(start_date_str)
                end_date = date.fromisoformat(end_date_str)
                is_default_view = False
                filter_type = 'date'
            except ValueError:
                pass 
        
        # 2. 其次使用疗程范围
        elif cycle_id:
            try:
                cycle = TreatmentCycle.objects.get(pk=cycle_id, patient=patient)
                start_date = cycle.start_date
                end_date = cycle.end_date if cycle.end_date else today
                is_default_view = False
                filter_type = 'cycle'
            except (TreatmentCycle.DoesNotExist, ValueError):
                pass

    # 3. 校验跨度（最大1年 = 366天）
    delta_days = (end_date - start_date).days
    if delta_days > 366:
        # 超过一年，强制截断为 start_date + 1年
        end_date = start_date + timedelta(days=365)
        delta_days = 365
    elif delta_days < 0:
        # 结束日期早于开始日期，重置为单日或默认
        end_date = start_date
        delta_days = 0

    # 构造查询用的 datetime (start 00:00:00 ~ end+1 00:00:00)
    # end_date 在界面上通常是包含的，所以查询时要加1天
    query_end_date = end_date + timedelta(days=1)
    
    start_dt = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))
    end_dt = timezone.make_aware(datetime.combine(query_end_date, datetime.min.time()))

    # 生成日期字符串列表 (MM-DD)
    # 如果跨年，可能需要显示年份，这里暂时保持 MM-DD，或者根据跨度决定
    date_fmt = "%m-%d"
    if start_date.year != end_date.year:
        date_fmt = "%Y-%m-%d"
        
    date_strs = [(start_date + timedelta(days=i)).strftime(date_fmt) for i in range(delta_days + 1)]

    # 1. 获取疗程列表
    cycles_page = get_treatment_cycles(patient, page=1, page_size=100)
    treatment_cycles = cycles_page.object_list

    # 2. 获取各指标数据
    charts = {}

    def get_daily_values(metric_type, value_key='value_main'):
        """获取指定指标范围内的每日数据（取每日最新一条）"""
        page = HealthMetricService.query_metrics_by_type(
            patient_id=patient.id,
            metric_type=metric_type,
            start_date=start_dt,
            end_date=end_dt,
            page_size=2000, # 足够大以覆盖数据
            sort_order='asc' # 按时间正序
        )
        
        data_map = {}
        for m in page.object_list:
            local_dt = timezone.localtime(m.measured_at)
            d_str = local_dt.strftime(date_fmt)
            val = getattr(m, value_key)
            if val is not None:
                data_map[d_str] = float(val)
        
        return [data_map.get(d, 0) for d in date_strs]

    # SpO2
    spo2_data = get_daily_values(MetricType.BLOOD_OXYGEN)
    charts['spo2'] = {
        "id": "chart-spo2",
        "title": "静息血氧 SpO2 (%)",
        "dates": date_strs,
        "series": [{"name": "静息血氧", "data": spo2_data, "color": "#3b82f6"}],
        "y_min": 80,
        "y_max": 100
    }

    # BP (需要主值和副值)
    bp_sbp = get_daily_values(MetricType.BLOOD_PRESSURE, 'value_main')
    bp_dbp = get_daily_values(MetricType.BLOOD_PRESSURE, 'value_sub')
    charts['bp'] = {
        "id": "chart-bp",
        "title": "血压 收缩压/舒张压 (mmHg)",
        "dates": date_strs,
        "series": [
            {"name": "收缩压", "data": bp_sbp, "color": "#3b82f6"},
            {"name": "舒张压", "data": bp_dbp, "color": "#10b981"}
        ],
        "y_min": 60,
        "y_max": 180
    }

    # Heart Rate
    hr_data = get_daily_values(MetricType.HEART_RATE)
    charts['hr'] = {
        "id": "chart-hr",
        "title": "静息心率 (次/min)",
        "dates": date_strs,
        "series": [{"name": "静息心率", "data": hr_data, "color": "#3b82f6"}],
        "y_min": 40,
        "y_max": 140
    }

    # Weight
    weight_data = get_daily_values(MetricType.WEIGHT)
    charts['weight'] = {
        "id": "chart-weight",
        "title": "体重 (KG)",
        "dates": date_strs,
        "series": [{"name": "体重", "data": weight_data, "color": "#3b82f6"}],
        "y_min": 40,
        "y_max": 120
    }

    # Temperature
    temp_data = get_daily_values(MetricType.BODY_TEMPERATURE)
    charts['temp'] = {
        "id": "chart-temp",
        "title": "体温 (℃)",
        "dates": date_strs,
        "series": [{"name": "体温", "data": temp_data, "color": "#3b82f6"}],
        "y_min": 35,
        "y_max": 42
    }

    # Steps
    steps_data = get_daily_values(MetricType.STEPS)
    charts['steps'] = {
        "id": "chart-steps",
        "title": "步数",
        "dates": date_strs,
        "series": [{"name": "步数", "data": steps_data, "color": "#3b82f6"}],
        "y_min": 0,
        "y_max": 15000 
    }

    # 3. 服药记录
    med_page = HealthMetricService.query_metrics_by_type(
        patient_id=patient.id,
        metric_type=MetricType.USE_MEDICATED,
        start_date=start_dt,
        end_date=end_dt,
        page_size=2000,
        sort_order='asc'
    )
    med_map = {}
    for m in med_page.object_list:
        local_dt = timezone.localtime(m.measured_at)
        d_str = local_dt.strftime(date_fmt)
        med_map[d_str] = True 

    medication_data = []
    med_count = 0
    for d in date_strs:
        taken = med_map.get(d, False)
        if taken:
            med_count += 1
        medication_data.append({
            "date": d,
            "taken": taken
        })
    
    total_days = len(date_strs)
    # compliance = int((med_count / total_days) * 100) if total_days > 0 else 0  # Deprecated: use real adherence data

    # 3.1 批量获取依从性数据 (Adherence Metrics)
    # 定义需要查询的指标类型映射
    chart_metric_map = {
        'spo2': MetricType.BLOOD_OXYGEN,
        'bp': MetricType.BLOOD_PRESSURE,
        'hr': MetricType.HEART_RATE,
        'weight': MetricType.WEIGHT,
        'temp': MetricType.BODY_TEMPERATURE,
        'steps': MetricType.STEPS
    }
    
    # 用药依从性使用 PlanItemCategory.MEDICATION
    med_type = choices.PlanItemCategory.MEDICATION
    
    # 构造查询列表
    types_to_query = [med_type] + list(chart_metric_map.values())
    
    # 尝试从缓存获取
    cache_key = f"adherence_metrics_{patient.id}_{start_date}_{end_date}"
    adherence_results = cache.get(cache_key)
    
    if not adherence_results:
        try:
            adherence_results = get_adherence_metrics_batch(
                patient=patient,
                adherence_types=types_to_query,
                start_date=start_date,
                end_date=end_date
            )
            # 缓存 5 分钟
            cache.set(cache_key, adherence_results, 300)
        except Exception as e:
            logger.error(f"Failed to fetch adherence metrics for patient {patient.id}: {e}")
            # 发生错误时，返回空列表，页面依从性将显示为 0%
            adherence_results = []
        
    # 将结果转换为字典以便查找
    adherence_map = {res['type']: res for res in adherence_results}
    
    # 更新用药依从性
    med_res = adherence_map.get(med_type)
    compliance = 0
    if med_res and med_res['rate'] is not None:
         compliance = int(med_res['rate'] * 100)
    
    # 更新各图表的依从性
    for key, metric_type in chart_metric_map.items():
        if key in charts:
            res = adherence_map.get(metric_type)
            rate = 0
            if res and res['rate'] is not None:
                rate = int(res['rate'] * 100)
            charts[key]['compliance'] = rate
    
    
    # ==========================================
    # 4. 随访问卷指标处理 (Questionnaire Indicators - Mock Data)
    # ==========================================    
    # TODO 随访问卷-体能评估、呼吸评估、咳嗽与痰色、食欲评估、疼痛量表、睡眠质量、心里痛苦分级评估，
    # TODO 1、筛选条件-按疗程选择或者按自定义日期选择，点击搜索按钮-根据日期进行筛选查询数据
    # TODO 2、咳嗽与痰色量表有个特殊情况，需要单独获取咳嗽与痰色随访问卷模块里的-咯血数据，问题：咳嗽或痰中是否带血？
    # TODO 去判断根据当前筛选条件日期，去查询这个数据，返回用户填写的这个问题选择的数据评分-前端去动态判断回显内容
    import random
    
    # 4.1 体能 (Q_PHYSICAL)
    # 模拟数据：0-4分
    phys_score_data = [random.randint(0, 4) for _ in date_strs]
    
    charts['physical'] = {
        "id": "chart-physical",
        "title": "体能评估",
        "dates": date_strs,
        "series": [
            {"name": "体能评分", "data": phys_score_data, "color": "#3b82f6"}, # Blue
        ],
        "y_min": 0,
        "y_max": 5
    }

    # 4.2 呼吸 (Q_BREATH - Mock, 假设与体能分开)
    breath_score_data = [random.randint(0, 4) for _ in date_strs]
    charts['breath'] = {
        "id": "chart-breath",
        "title": "呼吸评估",
        "dates": date_strs,
        "series": [
            {"name": "呼吸评分", "data": breath_score_data, "color": "#3b82f6"} # Teal
        ],
        "y_min": 0,
        "y_max": 5
    }

    # 4.2 咳嗽与痰色 (Q_COUGH)
    # 模拟数据：0-10分
    cough_score_data = [random.randint(0, 10) for _ in date_strs]
    
    # 模拟表格数据
    sputum_colors = ["无痰", "黄色", "脓色", "红色", "白色"]
    blood_status = ["是", "无"]
    
    sputum_table_row = [random.choice(sputum_colors) for _ in date_strs]
    blood_table_row = [random.choice(blood_status) for _ in date_strs]
        
    charts['cough'] = {
        "id": "chart-cough",
        "title": "",
        "dates": date_strs,
        "series": [{"name": "咳嗽评分", "data": cough_score_data, "color": "#3b82f6"}],
        "y_min": 0,
        "y_max": 12
    }
    
    cough_table = {
        "dates": date_strs,
        "rows": [
            {"label": "咯血", "values": blood_table_row}
        ]
    }

    # 4.3 食欲评估 (Q_APPETITE)
    # 模拟数据：0-10分
    app_data = [random.randint(0, 10) for _ in date_strs]
        
    charts['appetite'] = {
        "id": "chart-appetite",
        "title": "食欲评估",
        "dates": date_strs,
        "series": [{"name": "食欲评分", "data": app_data, "color": "#3b82f6"}],
        "y_min": 0,
        "y_max": 12
    }

    # 4.4 疼痛量表 (Q_PAIN)
    # 模拟数据：0-10分
    pain_data = [random.randint(0, 10) for _ in date_strs]
        
    charts['pain'] = {
        "id": "chart-pain",
        "title": "身体疼痛评估",
        "dates": date_strs,
        "series": [{"name": "身体疼痛评分", "data": pain_data, "color": "#3b82f6"}],
        "y_min": 0,
        "y_max": 10
    }
    
    # 4.5 睡眠质量 (Q_SLEEP)
    # 模拟数据：0-5分
    sleep_data = [random.randint(0, 5) for _ in date_strs]

    charts['sleep'] = {
        "id": "chart-sleep",
        "title": "睡眠质量评估",
        "dates": date_strs,
        "series": [{"name": "睡眠质量评分", "data": sleep_data, "color": "#3b82f6"}],
        "y_min": 0,
        "y_max": 6
    }
    
    # 4.6 心理痛苦分级 (Q_PSYCH)
    # 模拟数据：0-10分
    anxiety_data = [random.randint(0, 10) for _ in date_strs]

    charts['psych'] = {
        "id": "chart-psych",
        "title": "抑郁评估",
        "dates": date_strs,
        "series": [{"name": "抑郁评分", "data": anxiety_data, "color": "#3b82f6"}],
        "y_min": 0,
        "y_max": 10
    }
     # 4.7 焦虑评估 (Q_PSYCH)
    psych_data = [random.randint(0, 10) for _ in date_strs]

    charts['anxiety'] = {
        "id": "chart-anxiety",
        "title": "焦虑评估",
        "dates": date_strs,
        "series": [{"name": "焦虑评分", "data": psych_data, "color": "#3b82f6"}],
        "y_min": 0,
        "y_max": 10
    }
    return {
        "medication_data": medication_data,
        "medication_stats": {
            "count": med_count,
            "compliance": compliance
        },
        "charts": charts,
        "cough_table": cough_table, # 新增
        "treatment_cycles": treatment_cycles,
        "dates": date_strs,
        # 回显当前的筛选条件
        "current_cycle_id": int(cycle_id) if cycle_id else "",
        # 如果是默认视图（未筛选），则不回填日期到 input，显示为空；否则回填
        "current_start_date": start_date.isoformat() if not is_default_view else "",
        "current_end_date": end_date.isoformat() if not is_default_view else "",
        "is_default_view": is_default_view,
        "current_filter_type": filter_type or "",
    }
