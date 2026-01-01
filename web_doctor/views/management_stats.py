from typing import Any, Dict, Optional, List
from datetime import date
import random

class ManagementStatsView:
    def get_context_data(self, patient: Any, selected_package_id: Optional[int] = None) -> Dict[str, Any]:
        """
        获取管理统计页面的上下文数据
        """
        # TODO 获取患者服务包列表数据，服务包名称、服务包开始日期-结束日期
        # TODO 1、根据当前的服务包日期去查询管理数据概览、管理数据统计、咨询数据统计接口
        # TODO 2、管理数据概览模块：
        # TODO 显示药物调整次数、药物服务次数、服药已从率；指标监测项数量、指标记录次数、监测依从率
        # TODO 显示在线咨询次数、随访次数、复查次数、住院次数
        # 3、管理数据统计模块
        # 服药统计次数总量、图表数据，X轴：1-12月，Y轴：每月统计次数
        # 体温统计次数总量、图表数据，X轴：1-12月，Y轴：每月统计次数
        # 呼吸困难统计次数总量、图表数据，X轴：1-12月，Y轴：每月统计次数
        # 咳嗽程度统计次数总量、图表数据，X轴：1-12月，Y轴：每月统计次数
        # 痰色统计次数总量、图表数据，X轴：1-12月，Y轴：每月统计次数、
        # 疼痛量统计次数总量、图表数据，X轴：1-12月，Y轴：每月统计次数
        # 体重统计次数总量、图表数据，X轴：1-12月，Y轴：每月统计次数
        # 血氧统计次数总量、图表数据，X轴：1-12月，Y轴：每月统计次数
        # 血压统计次数总量、图表数据，X轴：1-12月，Y轴：每月统计次数
        # 心率统计次数总量、图表数据，X轴：1-12月，Y轴：每月统计次数
        # 3、咨询数据统计模块
        # 在线咨询次数总计数量
        # 按月统计咨询次数: X轴：1-12月，Y轴：每月咨询次数
        # 按时间段分布：
        # 按00:00-07:00的咨询次数
        # 按07:00-10:00的咨询次数
        # 按10:00-13:00的咨询次数
        # 按13:00-18:00的咨询次数
        # 按18:00-21:00的咨询次数
        # 按21:00-24:00的咨询次数
        
        # 模拟服务包数据
        service_packages = [
            {
                "id": 1,
                "name": "肺癌康复服务包",
                "start_date": "2025-09-21",
                "end_date": "2026-09-20",
                "is_active": False,
            },
            {
                "id": 2,
                "name": "肺癌康复服务包",
                "start_date": "2024-09-21",
                "end_date": "2025-09-20",
                "is_active": False,
            }
        ]

        # 设置选中状态
        if selected_package_id:
            for pkg in service_packages:
                if pkg["id"] == selected_package_id:
                    pkg["is_active"] = True
                    break
        else:
            # 默认选中第一个
            if service_packages:
                service_packages[0]["is_active"] = True

        # TODO 数据概览接口待联调 模拟统计概览数据
        stats_overview = {
            "medication_adjustment": 2,
            "medication_taken": 220,
            "medication_compliance": "89%",
            "indicators_monitoring": 7,
            "indicators_recorded": 200,
            "monitoring_compliance": "89%",
            "online_consultation": 35,
            "follow_up": 3,
            "checkup": 3,
            "hospitalization": 1,
        }

        # 生成图表数据
        # TODO 待联调管理数据统计接口
        charts = self._generate_charts_data()
        
        # 生成咨询数据
        # TODO 咨询数据统计接口待联调
        query_stats = self._generate_query_stats()

        return {
            "service_packages": service_packages,
            "stats_overview": stats_overview,
            "charts": charts,
            "query_stats": query_stats,
        }
    # TODO 数据统计接口待联调
    def _generate_charts_data(self) -> Dict[str, Any]:
        months = [f"{i}月" for i in range(1, 13)]
        
        def generate_series(min_val=0, max_val=30):
            # 模拟一个有起伏的数据
            data = []
            for i in range(12):
                if 3 <= i <= 9: # 4月到10月数据较高
                    val = random.randint(max_val - 5, max_val)
                else:
                    val = random.randint(min_val, min_val + 5)
                data.append(val)
            return data

        chart_configs = [
            ("medication", "服药统计次数", "次", "#3B82F6"), # Blue
            ("temp", "体温统计次数", "次", "#EF4444"), # Red
            ("dyspnea", "呼吸困难统计次数", "次", "#8B5CF6"), # Purple
            ("cough", "咳嗽程度统计次数", "次", "#F59E0B"), # Amber
            ("sputum", "痰色统计次数", "次", "#10B981"), # Emerald
            ("pain", "疼痛量表统计次数", "次", "#EC4899"), # Pink
            ("weight", "体重统计次数", "次", "#06B6D4"), # Cyan
            ("spo2", "血氧统计次数", "次", "#3B82F6"), # Blue
            ("bp", "血压统计次数", "次", "#6366F1"), # Indigo
            ("hr", "心率统计次数", "次", "#EF4444"), # Red
        ]

        charts = {}
        for key, title, unit, color in chart_configs:
            total_count = 100 # 模拟总次数
            if key == "medication": total_count = 220
            elif key == "temp": total_count = 110
            
            charts[key] = {
                "id": f"chart-{key}",
                "title": f"{title}: {total_count}{unit}",
                "subtitle": "",
                "dates": months,
                "y_min": 0,
                "y_max": 35,
                "series": [
                    {
                        "name": title,
                        "data": generate_series(),
                        "color": color
                    }
                ]
            }
        
        return charts

    def _generate_query_stats(self) -> Dict[str, Any]:
        """
        生成咨询数据统计
        """
        months = [f"{i}月" for i in range(1, 13)]
        
        # TODO 咨询数据统计接口待联调 模拟折线图数据：咨询次数随月份变化
        line_data = [0, 0, 0, 30, 31, 23, 26, 31, 27, 31, 5, 0] # 模拟数据，模仿图中趋势
        
        line_chart = {
            "id": "query-line-chart",
            "title": "按月统计",
            "xAxis": months,
            "yAxis": {"min": 0, "max": 35},
            "series": [
                {
                    "name": "咨询次数",
                    "data": line_data,
                    "color": "#3B82F6"
                }
            ]
        }
        
        # 模拟饼图数据：按时间段分布
        pie_data = [
            {"value": 1, "name": "00:00-07:00", "color": "#5B8FF9"},
            {"value": 1, "name": "07:00-10:00", "color": "#5AD8A6"},
            {"value": 8, "name": "10:00-13:00", "color": "#5D7092"},
            {"value": 10, "name": "13:00-18:00", "color": "#F6BD16"},
            {"value": 8, "name": "18:00-21:00", "color": "#E8684A"},
            {"value": 3, "name": "21:00-24:00", "color": "#D34949"},
        ]
        
        pie_chart = {
            "id": "query-pie-chart",
            "title": "按时间段分布",
            "series": pie_data
        }
        
        return {
            "total_count": 35,
            "line_chart": line_chart,
            "pie_chart": pie_chart
        }
