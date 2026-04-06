import logging
from datetime import date, timedelta, datetime
from decimal import Decimal, ROUND_CEILING, InvalidOperation
from django.db.models import Count, Q
from django.utils import timezone
from django.core.cache import cache
from core.models import DailyTask, TreatmentCycle, choices, QuestionnaireCode
from core.service.treatment_cycle import get_treatment_cycles as _get_treatment_cycles
from core.service.tasks import get_adherence_metrics_batch
from health_data.services.health_metric import HealthMetricService
from health_data.models.health_metric import MetricType
from health_data.models import QuestionnaireSubmission
from health_data.services.questionnaire_submission import QuestionnaireSubmissionService
from users.models import PatientProfile

logger = logging.getLogger(__name__)

_CYCLE_STATE_RANK = {
    "in_progress": 0,
    "not_started": 1,
    "completed": 2,
    "terminated": 3,
}


def _resolve_cycle_runtime_state(cycle: TreatmentCycle, today: date | None = None) -> str:
    if today is None:
        today = timezone.localdate()
    if cycle.status == choices.TreatmentCycleStatus.TERMINATED:
        return "terminated"
    if today < cycle.start_date:
        return "not_started"
    if cycle.end_date and today > cycle.end_date:
        return "completed"
    if cycle.status == choices.TreatmentCycleStatus.COMPLETED:
        return "completed"
    return "in_progress"


def _sort_cycles_for_indicators(cycles: list[TreatmentCycle], today: date | None = None) -> list[TreatmentCycle]:
    if today is None:
        today = timezone.localdate()
    indexed = list(enumerate(cycles))
    indexed.sort(
        key=lambda item: (
            _CYCLE_STATE_RANK[_resolve_cycle_runtime_state(item[1], today=today)],
            item[0],
        )
    )
    return [cycle for _, cycle in indexed]


def get_treatment_cycles(patient: PatientProfile, page: int = 1, page_size: int = 10):
    cycles_page = _get_treatment_cycles(patient, page=page, page_size=page_size)
    cycles = list(getattr(cycles_page, "object_list", []) or [])
    cycles_page.object_list = _sort_cycles_for_indicators(cycles, today=timezone.localdate())
    return cycles_page


def build_indicators_context(
    patient: PatientProfile,
    cycle_id: str | None = None,
    start_date_str: str | None = None,
    end_date_str: str | None = None,
    filter_type: str | None = None,
    review_subtypes: list[str] | None = None,
) -> dict:
    """
    构建“患者指标”Tab 所需的上下文数据：
    - 默认按日期查询最近30天
    - 支持按疗程筛选（手动）
    - 支持按日期筛选
    """
    today = timezone.localdate()
    default_start_date = today - timedelta(days=29)
    default_end_date = today

    def _parse_date_range(start_raw: str | None, end_raw: str | None) -> tuple[date, date] | None:
        if not start_raw or not end_raw:
            return None
        try:
            return date.fromisoformat(start_raw), date.fromisoformat(end_raw)
        except ValueError:
            return None

    # 1. 获取疗程列表
    cycles_page = get_treatment_cycles(patient, page=1, page_size=100)
    treatment_cycles = cycles_page.object_list

    # 初始化日期范围
    start_date: date | None = None
    end_date: date | None = None
    selected_cycle_id: str | None = None

    normalized_filter_type = filter_type if filter_type in {"cycle", "date"} else None
    is_default_view = False

    # 2. 解析筛选条件：
    # - cycle(有效) -> 用疗程起止
    # - cycle(无效) -> 回退最近30天，并归一为 date
    # - date(有效) -> 用传入日期
    # - date(无效) or filter_type 缺失 -> 最近30天
    if normalized_filter_type == "cycle":
        if cycle_id:
            try:
                cycle = TreatmentCycle.objects.get(pk=cycle_id, patient=patient)
                start_date = cycle.start_date
                end_date = cycle.end_date if cycle.end_date else today
                selected_cycle_id = str(cycle.id)
            except (TreatmentCycle.DoesNotExist, ValueError):
                start_date = default_start_date
                end_date = default_end_date
                normalized_filter_type = "date"
                is_default_view = True
        else:
            start_date = default_start_date
            end_date = default_end_date
            normalized_filter_type = "date"
            is_default_view = True
    elif normalized_filter_type == "date":
        parsed_range = _parse_date_range(start_date_str, end_date_str)
        if parsed_range:
            start_date, end_date = parsed_range
        else:
            start_date = default_start_date
            end_date = default_end_date
            is_default_view = True
    else:
        start_date = default_start_date
        end_date = default_end_date
        normalized_filter_type = "date"
        is_default_view = True

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

    display_date_fmt = "%m-%d"
    date_list = [start_date + timedelta(days=i) for i in range(delta_days + 1)]
    date_strs = [d.strftime(display_date_fmt) for d in date_list]

    # 2. 获取常规指标数据
    charts = {}

    def _to_decimal(value):
        if value is None:
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return None

    def _calc_dynamic_y_max(values, default_max, y_min, baselines=None, decimals=0):
        candidates = []
        for val in values or []:
            dec_val = _to_decimal(val)
            if dec_val is not None:
                candidates.append(dec_val)
        for baseline in baselines or []:
            dec_val = _to_decimal(baseline)
            if dec_val is not None:
                candidates.append(dec_val)

        if not candidates:
            return default_max

        raw_max = max(candidates)
        scaled = raw_max * Decimal("1.2")

        if decimals <= 0:
            y_max = scaled.to_integral_value(rounding=ROUND_CEILING)
            epsilon = Decimal("1")
        else:
            quant = Decimal("1").scaleb(-decimals)
            y_max = (scaled / quant).to_integral_value(rounding=ROUND_CEILING) * quant
            epsilon = quant

        y_min_dec = _to_decimal(y_min)
        if y_min_dec is not None and y_max < (y_min_dec + epsilon):
            y_max = y_min_dec + epsilon

        if decimals <= 0:
            try:
                return int(y_max)
            except (TypeError, ValueError):
                return int(y_max)
        return int(y_max)

    def get_daily_values(metric_type, value_key='value_main'):
        """获取指定指标范围内的每日数据（取每日最新一条）"""
        page = HealthMetricService.query_metrics_by_type(
            patient_id=patient.id,
            metric_type=metric_type,
            start_date=start_dt,
            end_date=end_dt,
            page_size=2000, 
            sort_order='asc' 
        )
        
        data_map = {}
        for m in page.object_list:
            local_dt = timezone.localtime(m.measured_at)
            d = local_dt.date()
            val = getattr(m, value_key)
            if val is not None:
                data_map[d] = float(val)
        
        series = [data_map.get(d, 0) for d in date_list]
        values = list(data_map.values())
        return series, values

    # SpO2
    spo2_data, spo2_values = get_daily_values(MetricType.BLOOD_OXYGEN)
    spo2_y_max = _calc_dynamic_y_max(
        spo2_values,
        default_max=100,
        y_min=80,
        baselines=[patient.baseline_blood_oxygen],
        decimals=0,
    )
    charts['spo2'] = {
        "id": "chart-spo2",
        "title": "静息血氧 SpO2 (%)",
        "dates": date_strs,
        "series": [
            {
                "name": "静息血氧",
                "data": spo2_data,
                "color": "#3b82f6",
                "baseline": patient.baseline_blood_oxygen,
            }
        ],
        "y_min": 80,
        "y_max": spo2_y_max
    }

    # BP (需要主值和副值)
    bp_sbp, bp_sbp_values = get_daily_values(MetricType.BLOOD_PRESSURE, 'value_main')
    bp_dbp, bp_dbp_values = get_daily_values(MetricType.BLOOD_PRESSURE, 'value_sub')
    bp_y_max = _calc_dynamic_y_max(
        bp_sbp_values + bp_dbp_values,
        default_max=220,
        y_min=40,
        baselines=[patient.baseline_blood_pressure_sbp, patient.baseline_blood_pressure_dbp],
        decimals=0,
    )
    charts['bp'] = {
        "id": "chart-bp",
        "title": "血压 收缩压/舒张压 (mmHg)",
        "dates": date_strs,
        "series": [
            {
                "name": "收缩压",
                "data": bp_sbp,
                "color": "#3b82f6",
                "baseline": patient.baseline_blood_pressure_sbp,
            },
            {
                "name": "舒张压",
                "data": bp_dbp,
                "color": "#10b981",
                "baseline": patient.baseline_blood_pressure_dbp,
            }
        ],
        "y_min": 40,
        "y_max": bp_y_max
    }

    # Heart Rate
    hr_data, hr_values = get_daily_values(MetricType.HEART_RATE)
    hr_y_max = _calc_dynamic_y_max(
        hr_values,
        default_max=180,
        y_min=40,
        baselines=[patient.baseline_heart_rate],
        decimals=0,
    )
    charts['hr'] = {
        "id": "chart-hr",
        "title": "静息心率 (次/min)",
        "dates": date_strs,
        "series": [
            {
                "name": "静息心率",
                "data": hr_data,
                "color": "#3b82f6",
                "baseline": patient.baseline_heart_rate,
            }
        ],
        "y_min": 40,
        "y_max": hr_y_max
    }

    # Weight
    weight_data, weight_values = get_daily_values(MetricType.WEIGHT)
    weight_y_max = _calc_dynamic_y_max(
        weight_values,
        default_max=150,
        y_min=30,
        baselines=[patient.baseline_weight],
        decimals=1,
    )
    charts['weight'] = {
        "id": "chart-weight",
        "title": "体重 (KG)",
        "dates": date_strs,
        "series": [
            {
                "name": "体重",
                "data": weight_data,
                "color": "#3b82f6",
                "baseline": patient.baseline_weight,
            }
        ],
        "y_min": 30,
        "y_max": weight_y_max
    }

    # Temperature
    temp_data, temp_values = get_daily_values(MetricType.BODY_TEMPERATURE)
    temp_y_max = _calc_dynamic_y_max(
        temp_values,
        default_max=42,
        y_min=34,
        baselines=[patient.baseline_body_temperature],
        decimals=1,
    )
    charts['temp'] = {
        "id": "chart-temp",
        "title": "体温 (℃)",
        "dates": date_strs,
        "series": [
            {
                "name": "体温",
                "data": temp_data,
                "color": "#3b82f6",
                "baseline": patient.baseline_body_temperature,
            }
        ],
        "y_min": 34,
        "y_max": temp_y_max
    }

    # Steps
    steps_data, steps_values = get_daily_values(MetricType.STEPS)
    steps_y_max = _calc_dynamic_y_max(
        steps_values,
        default_max=30000,
        y_min=0,
        baselines=[patient.baseline_steps],
        decimals=0,
    )
    charts['steps'] = {
        "id": "chart-steps",
        "title": "步数",
        "dates": date_strs,
        "series": [
            {
                "name": "步数",
                "data": steps_data,
                "color": "#3b82f6",
                "baseline": patient.baseline_steps,
            }
        ],
        "y_min": 0,
        "y_max": steps_y_max 
    }

    # 3. 服药记录
    # 口径说明：
    # 1) 当天无用药任务 -> 显示“无”
    # 2) 当天有用药任务且全部完成 -> 显示对勾
    # 3) 当天有用药任务但未全部完成 -> 显示 X
    med_task_daily = (
        DailyTask.objects.filter(
            patient=patient,
            task_type=choices.PlanItemCategory.MEDICATION,
            task_date__range=(start_date, end_date),
        )
        .values("task_date")
        .annotate(
            total_count=Count("id"),
            completed_count=Count("id", filter=Q(status=choices.TaskStatus.COMPLETED)),
        )
    )
    med_task_map = {}
    for row in med_task_daily:
        total_count = int(row.get("total_count") or 0)
        completed_count = int(row.get("completed_count") or 0)
        med_task_map[row["task_date"]] = {
            "has_task": total_count > 0,
            "completed_all": total_count > 0 and completed_count >= total_count,
        }

    medication_data = []
    med_count = 0
    # 重构 medication_data 循环，同时生成 display_date 和 real_date
    for day_date in date_list:
        d_str = day_date.strftime(display_date_fmt)
        day_task = med_task_map.get(day_date)
        has_task = bool(day_task and day_task.get("has_task"))

        if day_date > today:
            status = "future"
            taken = False
        elif not has_task:
            status = "none"
            taken = False
        else:
            taken = bool(day_task.get("completed_all"))
            status = "taken" if taken else "missed"
            if taken:
                med_count += 1

        medication_data.append({
            "date": day_date, # 真实日期对象，用于比较
            "display_date": d_str, # 显示用的格式化日期
            "taken": taken,
            "has_task": has_task,
            "status": status,
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
    # 4. 随访问卷指标处理 (Questionnaire Indicators - Real Data)
    # ==========================================
    
    def fetch_chart_data(code, title, y_min, y_max,series_name, color="#3b82f6"):
        submission_dates = None
        try:
            submission_times = QuestionnaireSubmission.objects.filter(
                patient_id=patient.id,
                questionnaire__code=code,
                created_at__gte=start_dt,
                created_at__lt=end_dt,
            ).values_list("created_at", flat=True)
            submission_dates = {
                timezone.localtime(created_at).date()
                for created_at in submission_times
            }
        except Exception as e:
            logger.error(f"Failed to fetch questionnaire submission dates for {code}: {e}")

        try:
            results = QuestionnaireSubmissionService.list_daily_questionnaire_scores(
                patient=patient,
                start_date=start_date,
                end_date=end_date,
                questionnaire_code=code,
            )
            # Map results to date_strs
            score_map = {res["date"]: res["score"] for res in results}
            data = []
            missing_flags = []
            has_submission_dates = submission_dates is not None
            submission_dates = submission_dates or set()
            for d in date_list:
                data.append(float(score_map.get(d, 0)))
                if has_submission_dates:
                    missing_flags.append(0 if d in submission_dates else 1)
                else:
                    missing_flags.append(0)
        except Exception as e:
            logger.error(f"Failed to fetch questionnaire scores for {code}: {e}")
            data = [0] * len(date_strs)
            missing_flags = [0] * len(date_strs)

        # Generate a unique ID based on code, handle special cases if needed (e.g. psych/depressive)
        chart_id_suffix = code.lower().replace("q_", "")
        if code == QuestionnaireCode.Q_DEPRESSIVE:
             chart_id_suffix = "psych" # maintain compatibility with template ID if needed, or just use 'psych' key
        
        return {
            "id": f"chart-{chart_id_suffix}", 
            "title": title,
            "dates": date_strs,
            "series": [{"name": series_name, "data": data, "missing": missing_flags, "color": color}],
            "y_min": y_min,
            "y_max": y_max
        }

    # 4.1 体能 (Q_PHYSICAL)
    charts['physical'] = fetch_chart_data(QuestionnaireCode.Q_PHYSICAL, "体能评估", 0,4, "体能评分")

    # 4.2 呼吸 (Q_BREATH)
    charts['breath'] = fetch_chart_data(QuestionnaireCode.Q_BREATH, "呼吸评估", 0,4, "呼吸评分")

    # 4.3 咳嗽与痰色 (Q_COUGH)
    charts['cough'] = fetch_chart_data(QuestionnaireCode.Q_COUGH, "", 0,15, "咳嗽评分")
    
    # 4.3.1 咯血表格 
    blood_table_row = []
    try:
        hemoptysis_flags = QuestionnaireSubmissionService.list_daily_cough_hemoptysis_flags(
            patient=patient,
            start_date=start_date,
            end_date=end_date,
        )
        
        # 将 boolean 转换为 "有"/"无"
        # True -> "有", False -> "无"
        # 结果映射到日期
        flag_map = {}
        for item in hemoptysis_flags:
            flag_map[item["date"]] = "有" if item["has_hemoptysis"] else "无"
            
        blood_table_row = [flag_map.get(d, "-") for d in date_list]
        
    except Exception as e:
        logger.error(f"Failed to fetch hemoptysis flags: {e}")
        blood_table_row = ["-"] * len(date_strs)

    cough_table = {
        "dates": date_strs,
        "rows": [
            {"label": "咯血", "values": blood_table_row}
        ]
    }

    # 4.4 食欲评估 (Q_APPETITE)
    charts['appetite'] = fetch_chart_data(QuestionnaireCode.Q_APPETITE, "食欲评估", 0,20, "食欲评分")

    # 4.5 疼痛量表 (Q_PAIN)
    charts['pain'] = fetch_chart_data(QuestionnaireCode.Q_PAIN, "身体疼痛评估", 0,36, "身体疼痛评分")

    # 4.6 睡眠质量 (Q_SLEEP)
    charts['sleep'] = fetch_chart_data(QuestionnaireCode.Q_SLEEP, "睡眠质量评估", 0,80, "睡眠质量评分")

    # 4.7 抑郁评估 (Q_DEPRESSIVE) -> Mapped to 'psych' key
    charts['psych'] = fetch_chart_data(QuestionnaireCode.Q_DEPRESSIVE, "抑郁评估", 0,27, "抑郁评分")
    # Override id to match template expectation if necessary (template uses chart-psych?)
    charts['psych']['id'] = "chart-psych"

    # 4.8 焦虑评估 (Q_ANXIETY)
    charts['anxiety'] = fetch_chart_data(QuestionnaireCode.Q_ANXIETY, "焦虑评估", 0,21, "焦虑评分")

    review_category_specs = [
        {
            "code": "blood_routine",
            "name": "血常规",
            "subtypes": [
                ("wbc", "白细胞计数"),
                ("rbc", "红细胞计数"),
                ("hgb", "血红蛋白"),
                ("hct", "红细胞压积"),
                ("plt", "血小板计数"),
                ("neu_pct", "中性粒细胞%"),
                ("lym_pct", "淋巴细胞%"),
                ("mon_pct", "单核细胞%"),
                ("eos_pct", "嗜酸性粒细胞%"),
                ("bas_pct", "嗜碱性粒细胞%"),
                ("mcv", "平均红细胞体积"),
                ("mch", "平均红细胞血红蛋白量"),
            ],
        },
        {
            "code": "biochemistry",
            "name": "血生化",
            "subtypes": [
                ("alt", "谷丙转氨酶 ALT"),
                ("ast", "谷草转氨酶 AST"),
                ("alp", "碱性磷酸酶 ALP"),
                ("tbil", "总胆红素 TBil"),
                ("alb", "白蛋白 ALB"),
                ("bun", "尿素氮 BUN"),
                ("cre", "肌酐 Cr"),
                ("ua", "尿酸 UA"),
                ("glu", "葡萄糖 GLU"),
                ("k", "钾 K"),
                ("na", "钠 Na"),
                ("cl", "氯 Cl"),
            ],
        },
        {
            "code": "tumor_marker",
            "name": "肿瘤标志物",
            "subtypes": [
                ("cea", "癌胚抗原 CEA"),
                ("cyfra21", "细胞角蛋白19片段 CYFRA21-1"),
                ("nse", "神经元特异性烯醇化酶 NSE"),
                ("progrp", "胃泌素释放肽前体 ProGRP"),
                ("scc", "鳞癌抗原 SCC"),
                ("ca125", "糖类抗原 CA125"),
                ("ca199", "糖类抗原 CA19-9"),
                ("ca153", "糖类抗原 CA15-3"),
                ("afp", "甲胎蛋白 AFP"),
                ("ferritin", "铁蛋白 Ferritin"),
            ],
        },
    ]
    subtype_meta = {}
    all_subtype_codes = []
    review_categories = []
    for category in review_category_specs:
        category_subtypes = []
        for subtype_code, subtype_name in category["subtypes"]:
            subtype_item = {"code": subtype_code, "name": subtype_name}
            category_subtypes.append(subtype_item)
            subtype_meta[subtype_code] = {
                "name": subtype_name,
                "category_code": category["code"],
                "category_name": category["name"],
            }
            all_subtype_codes.append(subtype_code)
        review_categories.append(
            {
                "code": category["code"],
                "name": category["name"],
                "subtypes": category_subtypes,
                "total_subtypes": len(category_subtypes),
            }
        )

    raw_selected_subtypes = review_subtypes or []
    normalized_selected_subtypes = []
    seen_codes = set()
    for subtype_code in raw_selected_subtypes:
        if subtype_code in subtype_meta and subtype_code not in seen_codes:
            normalized_selected_subtypes.append(subtype_code)
            seen_codes.add(subtype_code)

    review_palette = [
        "#2563eb",
        "#059669",
        "#ea580c",
        "#9333ea",
        "#db2777",
        "#0f766e",
        "#b45309",
        "#4f46e5",
    ]

    def _build_mock_followup_series(subtype_code: str) -> list[float]:
        code_seed = sum(ord(ch) for ch in subtype_code)
        base_value = 20 + (code_seed % 30)
        values = []
        for index, _ in enumerate(date_list):
            weekly_wave = ((index + (code_seed % 5)) % 7) - 3
            trend_value = (index * ((code_seed % 4) + 1)) / max(len(date_list), 1)
            current_value = round(base_value + weekly_wave * 0.8 + trend_value, 1)
            values.append(max(current_value, 0))
        return values

    review_series = []
    review_values = []
    for idx, subtype_code in enumerate(normalized_selected_subtypes):
        data_points = _build_mock_followup_series(subtype_code)
        review_values.extend(data_points)
        review_series.append(
            {
                "name": subtype_meta[subtype_code]["name"],
                "data": data_points,
                "color": review_palette[idx % len(review_palette)],
            }
        )

    review_y_max = _calc_dynamic_y_max(review_values, default_max=120, y_min=0, baselines=None, decimals=0)
    review_charts = []
    for idx, series_item in enumerate(review_series):
        single_chart_y_max = _calc_dynamic_y_max(
            series_item["data"],
            default_max=120,
            y_min=0,
            baselines=None,
            decimals=0,
        )
        review_charts.append(
            {
                "id": f"chart-followup-review-{idx}",
                "title": series_item["name"],
                "subtitle": f"{start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}",
                "dates": date_strs,
                "series": [series_item],
                "y_min": 0,
                "y_max": single_chart_y_max,
                "compliance": 0,
            }
        )

    focus_subtype_code = (
        normalized_selected_subtypes[0]
        if normalized_selected_subtypes
        else review_category_specs[0]["subtypes"][0][0]
    )
    focus_data = _build_mock_followup_series(focus_subtype_code)
    focus_latest_value = focus_data[-1] if focus_data else 0
    focus_prev_value = focus_data[-2] if len(focus_data) > 1 else focus_latest_value
    focus_delta = round(focus_latest_value - focus_prev_value, 1)
    review_indicator = {
        "module_title": "复查指标",
        "title": "核心关注指标",
        "focus_metric": {
            "code": focus_subtype_code,
            "name": subtype_meta[focus_subtype_code]["name"],
            "category_name": subtype_meta[focus_subtype_code]["category_name"],
            "current_value": focus_latest_value,
            "delta": focus_delta,
            "is_up": focus_delta >= 0,
        },
        "categories": review_categories,
        "selected_subtypes": normalized_selected_subtypes,
        "selected_count": len(normalized_selected_subtypes),
        "all_subtypes_count": len(all_subtype_codes),
        "selected_labels": [
            subtype_meta[subtype_code]["name"] for subtype_code in normalized_selected_subtypes[:6]
        ],
        "overflow_selected_count": max(len(normalized_selected_subtypes) - 6, 0),
        "chart": {
            "id": "chart-followup-review",
            "title": "复查子类型趋势",
            "subtitle": f"{start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}",
            "dates": date_strs,
            "series": review_series,
            "y_min": 0,
            "y_max": review_y_max,
            "compliance": 0,
        },
        "charts": review_charts,
    }

    return {
        "current_date": today, # 当前日期，用于模板比较
        "medication_data": medication_data,
        "medication_stats": {
            "count": med_count,
            "compliance": compliance
        },
        "charts": charts,
        "cough_table": cough_table,
        "treatment_cycles": treatment_cycles,
        "dates": date_strs,
        # 回显当前筛选条件：
        # - cycle 模式仅在有效疗程时带 current_cycle_id
        # - date 模式（含默认）始终回填日期
        "current_cycle_id": int(selected_cycle_id) if selected_cycle_id else "",
        "current_start_date": start_date.isoformat(),
        "current_end_date": end_date.isoformat(),
        "is_default_view": is_default_view,
        "current_filter_type": normalized_filter_type or "date",
        "review_indicator": review_indicator,
    }
