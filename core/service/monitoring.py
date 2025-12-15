"""Monitoring configuration related services."""

from __future__ import annotations

from typing import Any, Dict

from django.core.exceptions import ValidationError
from django.db import transaction

from core.models import MonitoringConfig
from users.models import PatientProfile


class MonitoringService:
    """Fat service managing MonitoringConfig operations."""

    @classmethod
    def init_patient_config(cls, patient: PatientProfile) -> MonitoringConfig:
        """
        初始化患者的监测配置。

        【业务规则】
        - 默认开启：体温 (enable_temp)、血压 (enable_bp)。
        - 默认关闭：体重、血氧、步数（由模型默认值决定）。
        """
        config, _ = MonitoringConfig.objects.get_or_create(
            patient=patient,
            defaults={"enable_temp": True, "enable_bp": True},
        )
        return config

    @classmethod
    @transaction.atomic
    def update_switches(
        cls,
        patient: PatientProfile,
        *,
        check_freq_days: int | None = None,
        enable_temp: bool,
        enable_spo2: bool,
        enable_weight: bool,
        enable_bp: bool,
        enable_step: bool,
    ) -> MonitoringConfig:
        """
        【功能说明】
        - 更新患者监测配置中的体温/血氧/体重/血压/步数开关，以及监测频率，保持“厚 service、薄视图”。
        - 以“全量更新”的方式写入当前配置（视图层应每次提交完整状态）。

        【参数说明】
        - patient: 目标患者档案对象，不能为空。
        - check_freq_days: 监测频率，单位为“天”，例如 1=每日、2=每2天。
        - enable_temp: 是否启用体温监测。
        - enable_spo2: 是否启用血氧监测。
        - enable_weight: 是否启用体重监测。
        - enable_bp: 是否启用血压监测。
        - enable_step: 是否启用步数监测。

        【返回参数说明】
        - 返回更新后的 MonitoringConfig 实例；若无配置则自动创建后再更新。
        """

        if patient is None:
            raise ValidationError("患者不能为空。")

        config, _ = MonitoringConfig.objects.get_or_create(patient=patient)

        # 开关字段统一组织在字典中，便于后续扩展
        update_map: Dict[str, Any] = {
            "enable_temp": enable_temp,
            "enable_spo2": enable_spo2,
            "enable_weight": enable_weight,
            "enable_bp": enable_bp,
            "enable_step": enable_step,
        }

        # 若显式传入监测频率，则一并纳入更新
        if check_freq_days is not None:
            update_map["check_freq_days"] = check_freq_days

        dirty_fields = [
            field for field, value in update_map.items() if getattr(config, field) != value
        ]
        if dirty_fields:
            for field in dirty_fields:
                setattr(config, field, update_map[field])
            config.save(update_fields=dirty_fields)
        return config

    @classmethod
    @transaction.atomic
    def touch_last_generated_dates(
        cls,
        patient: PatientProfile,
        *,
        temp_date=None,
        spo2_date=None,
        weight_date=None,
        bp_date=None,
        step_date=None,
    ) -> MonitoringConfig:
        """
        【功能说明】
        - 更新监测配置中各指标的上次任务生成日期，仅对显式传入的字段生效。

        【参数说明】
        - patient: 目标患者档案对象，不能为空。
        - temp_date/spo2_date/weight_date/bp_date/step_date: 对应指标的日期值，默认为 None 表示忽略。

        【返回参数说明】
        - 返回更新后的 MonitoringConfig 实例，未传入的字段保持原状。
        """

        if patient is None:
            raise ValidationError("患者不能为空。")

        config, _ = MonitoringConfig.objects.get_or_create(patient=patient)
        update_map = {
            "last_gen_date_temp": temp_date,
            "last_gen_date_spo2": spo2_date,
            "last_gen_date_weight": weight_date,
            "last_gen_date_bp": bp_date,
            "last_gen_date_step": step_date,
        }
        dirty_fields = [field for field, value in update_map.items() if value is not None]
        if dirty_fields:
            for field in dirty_fields:
                setattr(config, field, update_map[field])
            config.save(update_fields=dirty_fields)
        return config
