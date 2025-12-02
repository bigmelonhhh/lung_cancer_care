"""Monitoring configuration related services."""

from __future__ import annotations

from typing import Dict

from django.core.exceptions import ValidationError
from django.db import transaction

from core.models import MonitoringConfig
from users.models import PatientProfile


class MonitoringService:
    """Fat service managing MonitoringConfig operations."""

    @classmethod
    @transaction.atomic
    def update_switches(
        cls,
        patient: PatientProfile,
        *,
        enable_temp: bool,
        enable_spo2: bool,
        enable_weight: bool,
        enable_bp: bool,
        enable_step: bool,
    ) -> MonitoringConfig:
        """
        【功能说明】
        - 更新患者监测配置中的体温/血氧/体重/血压/步数开关，保持“厚 service、薄视图”。
        - 5个参数一次全量更新

        【参数说明】
        - patient: 目标患者档案对象，不能为空。
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
        update_map: Dict[str, bool] = {
            "enable_temp": enable_temp,
            "enable_spo2": enable_spo2,
            "enable_weight": enable_weight,
            "enable_bp": enable_bp,
            "enable_step": enable_step,
        }

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
