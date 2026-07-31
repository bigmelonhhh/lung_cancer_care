"""一般监测指标的共享展示与路由定义。"""

from __future__ import annotations

from dataclasses import dataclass

from health_data.models import MetricType


@dataclass(frozen=True)
class MonitoringMetricDefinition:
    slug: str
    metric_type: str
    title: str
    monitoring_name: str
    unit: str
    icon_key: str
    home_type: str
    home_subtitle: str
    chart_key: str
    chart_color: str
    chart_default_max: int
    decimal_places: int
    title_keywords: tuple[str, ...]
    show_in_home_list: bool = True
    record_route_name: str | None = None
    record_route_slug: str | None = None


_DEFINITIONS = (
    MonitoringMetricDefinition("bp", MetricType.BLOOD_PRESSURE, "血压", "血压监测", "mmHg", "bp", "bp_hr", "请记录今日血压心率情况", "bp", "#3b82f6", 220, 0, ("血压",), record_route_name="web_patient:record_bp"),
    MonitoringMetricDefinition("spo2", MetricType.BLOOD_OXYGEN, "血氧", "血氧监测", "%", "spo2", "spo2", "请记录今日血氧饱和度", "spo2", "#3b82f6", 100, 0, ("血氧",), record_route_name="web_patient:record_spo2"),
    MonitoringMetricDefinition("heart", MetricType.HEART_RATE, "心率", "心率监测", "bpm", "heart", "bp_hr", "请记录今日血压心率情况", "hr", "#3b82f6", 180, 0, ("心率",), record_route_name="web_patient:record_bp"),
    MonitoringMetricDefinition("step", MetricType.STEPS, "步数", "步数监测", "步", "step", "step", "请记录今日步数", "steps", "#3b82f6", 30000, 0, ("步数",), False),
    MonitoringMetricDefinition("weight", MetricType.WEIGHT, "体重", "体重监测", "kg", "weight", "weight", "请记录今日体重", "weight", "#3b82f6", 150, 1, ("体重",), record_route_name="web_patient:record_weight"),
    MonitoringMetricDefinition("temperature", MetricType.BODY_TEMPERATURE, "体温", "体温监测", "℃", "temperature", "temperature", "请记录今日体温", "temp", "#3b82f6", 42, 1, ("体温",), record_route_name="web_patient:record_temperature"),
    MonitoringMetricDefinition("glucose", MetricType.BLOOD_GLUCOSE, "血糖", "血糖监测", "mmol/L", "glucose", "glucose", "请记录今日血糖", "glucose", "#f472b6", 20, 1, ("血糖",), record_route_name="web_patient:record_general_monitoring", record_route_slug="glucose"),
    MonitoringMetricDefinition("ketone", MetricType.BLOOD_KETONE, "血酮", "血酮监测", "mmol/L", "ketone", "ketone", "请记录今日血酮", "ketone", "#2563eb", 5, 1, ("血酮", "酮体"), record_route_name="web_patient:record_general_monitoring", record_route_slug="ketone"),
    MonitoringMetricDefinition("uric_acid", MetricType.URIC_ACID, "尿酸", "尿酸监测", "μmol/L", "uric_acid", "uric_acid", "请记录今日尿酸", "uric_acid", "#ff5858", 800, 0, ("尿酸",), record_route_name="web_patient:record_general_monitoring", record_route_slug="uric_acid"),
)

MONITORING_DEFINITIONS_BY_SLUG = {item.slug: item for item in _DEFINITIONS}
MONITORING_DEFINITIONS_BY_METRIC_TYPE = {
    item.metric_type: item for item in _DEFINITIONS
}


def get_monitoring_definitions() -> tuple[MonitoringMetricDefinition, ...]:
    return _DEFINITIONS


def get_monitoring_definition_by_slug(slug: str) -> MonitoringMetricDefinition:
    return MONITORING_DEFINITIONS_BY_SLUG[slug]


def get_monitoring_definition_by_metric_type(
    metric_type: str,
) -> MonitoringMetricDefinition:
    return MONITORING_DEFINITIONS_BY_METRIC_TYPE[metric_type]


def resolve_monitoring_definition(
    *,
    metric_type: str | None = None,
    title: str = "",
) -> MonitoringMetricDefinition | None:
    if metric_type:
        definition = MONITORING_DEFINITIONS_BY_METRIC_TYPE.get(metric_type)
        if definition:
            return definition
    normalized_title = title or ""
    for definition in _DEFINITIONS:
        if any(keyword in normalized_title for keyword in definition.title_keywords):
            return definition
    return None
