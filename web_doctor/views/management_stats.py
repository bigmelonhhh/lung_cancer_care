import logging
from typing import Any, Dict, Optional, List
from datetime import date
import random
from django.db.models import Count
from django.db.models.functions import TruncMonth
from django.utils import timezone
import datetime

from market.service.order import get_paid_orders_for_patient
from core.service.tasks import get_adherence_metrics, MONITORING_ADHERENCE_ALL
from health_data.services.health_metric import HealthMetricService
from core.models.choices import PlanItemCategory
from health_data.models import MetricType, QuestionnaireSubmission
from django.contrib.auth.decorators import login_required
from users.decorators import check_doctor_or_assistant
from chat.services.chat import ChatService

class ManagementStatsView:
    def get_context_data(self, patient: Any, selected_package_id: Optional[int] = None) -> Dict[str, Any]:
        """
        获取管理统计页面的上下文数据
        """
        # 获取真实服务包数据（已支付订单）
        orders = get_paid_orders_for_patient(patient)
        service_packages = []
        for order in orders:
            service_packages.append({
                "id": order.id,
                "name": order.product.name,
                "start_date": order.start_date,
                "end_date": order.end_date,
                "is_active": False,
            })

        # 确定选中的服务包及时间范围
        active_package = None
        start_date = None
        end_date = None

        if service_packages:
            if selected_package_id:
                for pkg in service_packages:
                    if pkg["id"] == selected_package_id:
                        pkg["is_active"] = True
                        active_package = pkg
                        break
            
            # 如果没有找到选中的（或未提供ID），默认选中第一个
            if not active_package:
                service_packages[0]["is_active"] = True
                active_package = service_packages[0]
            
            start_date = active_package["start_date"]
            end_date = active_package["end_date"]

        # 管理数据概览
        stats_overview = {
            "medication_adjustment": 0, 
            "medication_taken": 0,
            "medication_compliance": "0%",
            "indicators_monitoring": 0,
            "indicators_recorded": 0,
            "monitoring_compliance": "0%",
            "online_consultation": 0,
            "follow_up": 0,
            "checkup": 0,
            "hospitalization": 0,
        }

        if start_date and end_date:
            # 1. 药物相关统计
            med_metrics = get_adherence_metrics(
                patient_id=patient.id,
                adherence_type=PlanItemCategory.MEDICATION,
                start_date=start_date,
                end_date=end_date
            )
            stats_overview["medication_taken"] = med_metrics.get("completed", 0)
            med_rate = med_metrics.get("rate")
            if med_rate is not None:
                stats_overview["medication_compliance"] = f"{int(med_rate * 100)}%"

            # 2. 监测相关统计
            # 监测依从性
            mon_metrics = get_adherence_metrics(
                patient_id=patient.id,
                adherence_type=MONITORING_ADHERENCE_ALL,
                start_date=start_date,
                end_date=end_date
            )
            stats_overview["indicators_monitoring"] = mon_metrics.get("total", 0)
            mon_rate = mon_metrics.get("rate")
            if mon_rate is not None:
                stats_overview["monitoring_compliance"] = f"{int(mon_rate * 100)}%"
            
            # 监测记录数 (实际上传量)
            record_count = HealthMetricService.count_metric_uploads(
                patient=patient,
                metric_type=MONITORING_ADHERENCE_ALL,
                start_date=start_date,
                end_date=end_date
            )
            stats_overview["indicators_recorded"] = record_count

        # 生成图表数据
        charts = self._generate_charts_data(patient, start_date, end_date)
        
        # 生成咨询数据统计
        query_stats = self._generate_query_stats(patient, start_date, end_date)

        return {
            "service_packages": service_packages,
            "stats_overview": stats_overview,
            "charts": charts,
            "query_stats": query_stats,
        }
    
    def _generate_charts_data(self, patient: Any, start_date: date | None, end_date: date | None) -> Dict[str, Any]:
        """
        生成管理数据统计图表数据
        """
        chart_configs = [
            ("medication", "服药统计次数", "次", "#9BB711", MetricType.USE_MEDICATED),
            ("temp", "体温统计次数", "次", "#EF4444", MetricType.BODY_TEMPERATURE),
            ("spo2", "血氧统计次数", "次", "#3B82F6", MetricType.BLOOD_OXYGEN),
            ("bp", "血压统计次数", "次", "#6366F1", MetricType.BLOOD_PRESSURE),
            ("hr", "心率统计次数", "次", "#EFA244", MetricType.HEART_RATE),
            ("weight", "体重统计次数", "次", "#06B6D4", MetricType.WEIGHT),
            ("step", "步数统计次数", "次", "#09D406", MetricType.STEPS),
            ("stamina", "体能评分统计次数", "次", "#5CC3F6", "Q_PHYSICAL"),
            ("dyspnea", "呼吸困难统计次数", "次", "#8B5CF6", "Q_BREATH"),
            ("cough", "咳嗽与痰色统计次数", "次", "#F59E0B", "Q_COUGH"),
            ("sputum", "食欲统计次数", "次", "#10B981", "Q_APPETITE"), 
            ("pain", "身体疼痛统计次数", "次", "#EC4899", "Q_PAIN"),
            ("sleep", "睡眠质量统计次数", "次", "#82E608", "Q_SLEEP"),
            ("depressed", "抑郁评估统计次数", "次", "#4861EC", "Q_DEPRESSIVE"),
            ("anxiety", "焦虑统计次数", "次", "#48B8EC", "Q_ANXIETY"),
        ]

        charts = {}
        
        # 初始化默认数据（空数据）
        # 默认显示月份（如果无日期，默认显示当前年1-12月? 或者空列表?）
        # 如果没有 start_date，则无法确定月份范围。这里我们假设如果没数据，就显示当前年的月份
        months = []
        if start_date and end_date:
            curr = date(start_date.year, start_date.month, 1)
            end = date(end_date.year, end_date.month, 1)
            while curr <= end:
                months.append(f"{curr.year}-{curr.month:02d}")
                if curr.month == 12:
                    curr = date(curr.year + 1, 1, 1)
                else:
                    curr = date(curr.year, curr.month + 1, 1)
        else:
            # 默认显示空
            months = []

        # 准备批量查询的数据源
        all_types_to_query = []
        config_map = {} # key -> (title, unit, color, type/code)

        for key, title, unit, color, type_code in chart_configs:
            config_map[key] = (title, unit, color, type_code)
            all_types_to_query.append(type_code)

        # 获取数据
        combined_data = {}

        if start_date and end_date and all_types_to_query:
            try:
                # 统一调用接口获取所有类型（指标+问卷）的数据
                combined_data = HealthMetricService.count_metric_uploads_by_month(
                    patient, list(set(all_types_to_query)), start_date, end_date
                )
            except Exception:
                combined_data = {}

        # 组装图表
        for key, title, unit, color, type_code in chart_configs:
            series_data = []
            total_count = 0
            
            # 查找数据
            data_list = combined_data.get(type_code, [])
            
            # 将 data_list (dict list) 转换为按 months 顺序的 list
            # 建立 month -> count 映射
            count_map = {item['month']: item['count'] for item in data_list}
            
            for m in months:
                count = count_map.get(m, 0)
                series_data.append(count)
                total_count += count
            
            charts[key] = {
                "id": f"chart-{key}",
                "title": f"{title}: {total_count}{unit}",
                "subtitle": "",
                "dates": months,
                "y_min": 0,
                "y_max": max(series_data) + 5 if series_data else 10, # 动态调整 Y 轴
                "series": [
                    {
                        "name": title,
                        "data": series_data,
                        "color": color
                    }
                ]
            }
        
        return charts

    def _generate_query_stats(self, patient: Any, start_date: date | None, end_date: date | None) -> Dict[str, Any]:
        """
        生成咨询数据统计
        """
        # 默认空数据结构
        empty_result = {
            "total_count": 0,
            "line_chart": {
                "id": "query-line-chart",
                "title": "按月统计",
                "xAxis": [],
                "yAxis": {"min": 0, "max": 10},
                "series": [{"name": "咨询次数", "data": [], "color": "#3B82F6"}]
            },
            "pie_chart": {
                "id": "query-pie-chart",
                "title": "按时间段分布",
                "series": []
            }
        }

        if not patient or not start_date or not end_date:
            return empty_result

        try:
            chat_service = ChatService()
            stats = chat_service.get_patient_chat_session_stats(
                patient=patient,
                start_date=start_date,
                end_date=end_date
            )
            # logging.info(f"数据: {stats}")
        except Exception as e:
            # 如果服务调用失败，返回空数据
            return empty_result

        # 1. 处理折线图数据 (按月统计)
        months = []
        curr = date(start_date.year, start_date.month, 1)
        end = date(end_date.year, end_date.month, 1)
        while curr <= end:
            months.append(f"{curr.year}-{curr.month:02d}")
            if curr.month == 12:
                curr = date(curr.year + 1, 1, 1)
            else:
                curr = date(curr.year, curr.month + 1, 1)

        monthly_data = stats.get("monthly", [])
        monthly_map = {item["month"]: item["count"] for item in monthly_data}
        
        line_series_data = []
        for m in months:
            line_series_data.append(monthly_map.get(m, 0))
            
        line_chart = {
            "id": "query-line-chart",
            "title": "按月统计",
            "xAxis": months,
            "yAxis": {"min": 0, "max": max(line_series_data) + 5 if line_series_data else 10},
            "series": [
                {
                    "name": "咨询次数",
                    "data": line_series_data,
                    "color": "#3B82F6"
                }
            ]
        }

        # 2. 处理饼图数据 (按时段分布)
        time_slots = stats.get("time_slots", {})
        # 映射配置: key -> (name, color)
        slot_config = {
            "0-7": ("00:00-07:00", "#5B8FF9"),
            "7-10": ("07:00-10:00", "#5AD8A6"),
            "10-13": ("10:00-13:00", "#5D7092"),
            "13-18": ("13:00-18:00", "#F6BD16"),
            "18-21": ("18:00-21:00", "#E8684A"),
            "21-24": ("21:00-24:00", "#D34949"),
        }
        
        pie_series_data = []
        # 按固定顺序生成饼图数据
        ordered_keys = ["0-7", "7-10", "10-13", "13-18", "18-21", "21-24"]
        
        for key in ordered_keys:
            count = time_slots.get(key, 0)
            if count > 0: # 仅展示有数据的时段，或者全部展示？原Mock是全部展示，这里保留全部展示逻辑会更好看，但通常饼图只展示有值的。
                # 再次参考原Mock，全部都有值。为了饼图美观，如果全是0则空。
                # 但为了图例完整，我们构造所有，ECharts会自动处理0值。
                name, color = slot_config.get(key, (key, "#ccc"))
                pie_series_data.append({
                    "value": count,
                    "name": name,
                    "color": color
                })
        
        # 如果全是0，可能不想显示？保留0值也没关系。

        pie_chart = {
            "id": "query-pie-chart",
            "title": "按时间段分布",
            "series": pie_series_data
        }

        return {
            "total_count": stats.get("total", 0),
            "line_chart": line_chart,
            "pie_chart": pie_chart
        }
