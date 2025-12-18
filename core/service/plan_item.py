"""Plan item service layer providing fat service logic for treatment plans."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from django.core.exceptions import ValidationError
from django.db import transaction

from core.models import (
    CheckupLibrary,
    Questionnaire,
    Medication,
    PlanItem,
    TreatmentCycle,
    choices,
)


class PlanItemService:
    """Service layer for CRUD-like interactions on plan items."""

    @classmethod
    def get_cycle_plan_view(cls, cycle_id: int) -> Dict[str, Any]:
        """
        【功能说明】
        - 聚合同一疗程下的药物/检查/问卷标准库与既有计划条目，生成前端可直接渲染的配置视图。

        【参数说明】
        - cycle_id: TreatmentCycle 主键 ID。

        【返回参数说明】
        - dict，包含 cycle 基本信息以及 medications/checkups/questionnaires 三个列表。
          每个列表元素兼具标准库信息和对应 PlanItem 状态（plan_item_id、is_active、schedule_days 等）。
        """

        cycle = cls._get_cycle(cycle_id)
        plan_items = list(
            PlanItem.objects.filter(cycle=cycle).select_related("medicine", "checkup", "questionnaire")
        )
        med_map = {pi.medicine_id: pi for pi in plan_items if pi.medicine_id}
        checkup_map = {pi.checkup_id: pi for pi in plan_items if pi.checkup_id}
        questionnaire_map = {pi.questionnaire_id: pi for pi in plan_items if pi.questionnaire_id}

        medications = [
            cls._build_med_payload(med, med_map.get(med.id))
            for med in Medication.objects.filter(is_active=True).order_by("name")
        ]
        checkups = [
            cls._build_checkup_payload(chk, checkup_map.get(chk.id))
            for chk in CheckupLibrary.objects.filter(is_active=True).order_by("sort_order", "name")
        ]
        questionnaires = [
            cls._build_questionnaire_payload(q, questionnaire_map.get(q.id))
            for q in Questionnaire.objects.filter(is_active=True).order_by("sort_order", "name")
        ]

        return {
            "cycle": {
                "id": cycle.id,
                "name": cycle.name,
                "start_date": cycle.start_date,
                "end_date": cycle.end_date,
                "cycle_days": cycle.cycle_days,
                "status": cycle.status,
                "is_finished": cycle.is_finished,
            },
            "medications": medications,
            "checkups": checkups,
            "questionnaires": questionnaires,
        }

    @classmethod
    @transaction.atomic
    def toggle_item_status(
        cls,
        cycle_id: int,
        category: int,
        library_id: int,
        enable: bool,
    ) -> PlanItem | None:
        """
        【功能说明】
        - 切换某个标准库条目在指定疗程下的启用/停用状态，并在必要时创建或同步 PlanItem。

        【参数说明】
        - cycle_id: 所属疗程 ID。
        - category: 计划类型（PlanItemCategory 枚举值）。
        - library_id: 标准库记录 ID（药物/检查/问卷）。
        - enable: True 表示开启，False 表示关闭。

        【返回参数说明】
        - 更新后的 PlanItem 实例；若 enable=False 且原本不存在记录，则返回 None。
        """

        cycle = cls._get_cycle(cycle_id)
        library_field, library_model = cls._get_library_binding(category)
        plan = cls._get_plan_item(cycle_id, category, library_field, library_id)

        if enable:
            library_obj = cls._get_library_instance(library_model, library_id)
            schedule_template = list(library_obj.schedule_days_template or [])
            # 仅保留“今天及之后”的执行日，历史执行日不会出现在新建计划中
            current_day = cls._get_current_day_index_for_cycle(cycle)
            schedule_template = [d for d in schedule_template if d >= current_day]
            if plan is None:
                plan = PlanItem.objects.create(
                    cycle=cycle,
                    category=category,
                    item_name=library_obj.name,
                    status=choices.PlanItemStatus.ACTIVE,
                    schedule_days=schedule_template,
                    interaction_config=cls._build_interaction_config(category, library_obj),
                    **cls._build_library_fk_kwargs(category, library_obj),
                    **cls._build_default_snapshot(category, library_obj),
                )
            else:
                updates = {"status": choices.PlanItemStatus.ACTIVE}
                if not plan.schedule_days:
                    # 重新开启且当前计划尚无执行日时，同样只使用“今天及之后”的模板
                    updates["schedule_days"] = schedule_template
                for field, value in updates.items():
                    setattr(plan, field, value)
                plan.save(update_fields=list(updates.keys()))
        else:
            if plan:
                # 关闭计划时，仅清除“今天及之后”的 schedule，历史保留
                current_day = cls._get_current_day_index_for_cycle(plan.cycle)
                schedule = list(plan.schedule_days or [])
                if schedule:
                    schedule = [d for d in schedule if d < current_day]
                plan.status = choices.PlanItemStatus.DISABLED
                plan.schedule_days = schedule
                plan.save(update_fields=["status", "schedule_days"])
        return plan

    @classmethod
    @transaction.atomic
    def toggle_schedule_day(cls, plan_item_id: int, day: int, checked: bool) -> PlanItem:
        """
        【功能说明】
        - 处理 D1/D2 等具体执行日的勾选/取消，并根据操作自动维护 PlanItem 的状态。

        【参数说明】
        - plan_item_id: 计划条目 ID。
        - day: 要操作的天数（DayIndex）。
        - checked: True=勾选、False=取消。

        【返回参数说明】
        - 更新后的 PlanItem 实例。
        """

        plan = cls._get_plan_by_id(plan_item_id)
        cls._validate_day(plan, day)

        # 已经过了的执行日不可再修改（历史只读）
        current_day = cls._get_current_day_index_for_cycle(plan.cycle)
        if day < current_day:
            return plan
        schedule = list(plan.schedule_days or [])
        if checked:
            if day not in schedule:
                schedule.append(day)
                schedule.sort()
            plan.schedule_days = schedule
            if plan.status == choices.PlanItemStatus.DISABLED:
                plan.status = choices.PlanItemStatus.ACTIVE
        else:
            if day in schedule:
                schedule.remove(day)
                plan.schedule_days = schedule
        plan.save(update_fields=["schedule_days", "status"] if checked else ["schedule_days"])
        return plan

    @classmethod
    def update_item_field(cls, plan_item_id: int, field_name: str, value: Any) -> PlanItem:
        """
        【功能说明】
        - 更新指定 PlanItem 的剂量、用法、优先级或交互配置等文本/配置字段。

        【参数说明】
        - plan_item_id: 计划条目 ID。
        - field_name: 允许修改的字段名（drug_dosage、drug_usage、priority_level、interaction_config）。
        - value: 新值，由前端保证格式正确。

        【返回参数说明】
        - 更新后的 PlanItem 实例。
        """

        allowed_fields = {"drug_dosage", "drug_usage", "priority_level", "interaction_config"}
        if field_name not in allowed_fields:
            raise ValidationError("不支持修改该字段。")
        plan = cls._get_plan_by_id(plan_item_id)
        setattr(plan, field_name, value)
        plan.save(update_fields=[field_name])
        return plan

    @classmethod
    def toggle_questionnaire_detail(cls, plan_item_id: int, code: str, enabled: bool) -> PlanItem:
        """
        【功能说明】
        - 更新问卷计划条目的 interaction_config 中的 details 配置。
        - 用于控制问卷中特定模块/问题的开启状态。
        """
        plan = cls._get_plan_by_id(plan_item_id)

        # 确保 interaction_config 及其 details 字典存在
        config = plan.interaction_config or {}
        details = config.get("details", {})

        # 更新状态
        if enabled:
            details[code] = True
        else:
            details[code] = False

        config["details"] = details
        plan.interaction_config = config
        plan.save(update_fields=["interaction_config"])
        return plan

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _get_cycle(cycle_id: int) -> TreatmentCycle:
        try:
            return TreatmentCycle.objects.get(pk=cycle_id)
        except TreatmentCycle.DoesNotExist as exc:
            raise ValidationError("疗程不存在。") from exc

    @staticmethod
    def _get_plan_by_id(plan_item_id: int) -> PlanItem:
        try:
            return PlanItem.objects.select_related("cycle").get(pk=plan_item_id)
        except PlanItem.DoesNotExist as exc:
            raise ValidationError("计划条目不存在。") from exc

    @classmethod
    def _get_plan_item(
        cls,
        cycle_id: int,
        category: int,
        library_field: str,
        library_id: int,
    ) -> Optional[PlanItem]:
        filters = {
            "cycle_id": cycle_id,
            "category": category,
            library_field: library_id,
        }
        return PlanItem.objects.filter(**filters).first()

    @staticmethod
    def _get_library_binding(category: int) -> Tuple[str, type]:
        if category == choices.PlanItemCategory.MEDICATION:
            return "medicine_id", Medication
        if category == choices.PlanItemCategory.CHECKUP:
            return "checkup_id", CheckupLibrary
        if category == choices.PlanItemCategory.QUESTIONNAIRE:
            return "questionnaire_id", Questionnaire
        raise ValidationError("无效的计划类型。")

    @staticmethod
    def _get_library_instance(model_cls, library_id: int):
        try:
            obj = model_cls.objects.get(pk=library_id)
        except model_cls.DoesNotExist as exc:  # type: ignore[attr-defined]
            raise ValidationError("标准库记录不存在。") from exc
        if hasattr(obj, "is_active") and not obj.is_active:
            raise ValidationError("该标准库记录已停用。")
        return obj

    @staticmethod
    def _build_library_fk_kwargs(category: int, library_obj) -> Dict[str, Any]:
        if category == choices.PlanItemCategory.MEDICATION:
            return {"medicine": library_obj}
        if category == choices.PlanItemCategory.CHECKUP:
            return {"checkup": library_obj}
        if category == choices.PlanItemCategory.QUESTIONNAIRE:
            return {"questionnaire": library_obj}
        return {}

    @staticmethod
    def _build_default_snapshot(category: int, library_obj) -> Dict[str, Any]:
        if category == choices.PlanItemCategory.MEDICATION:
            return {
                "drug_dosage": library_obj.default_dosage or "",
                "drug_usage": library_obj.default_frequency or "",
            }
        return {"drug_dosage": "", "drug_usage": ""}

    @staticmethod
    def _build_interaction_config(category: int, library_obj) -> Dict[str, Any]:
        if category == choices.PlanItemCategory.CHECKUP and getattr(library_obj, "related_report_type", None):
            return {"related_report_type": library_obj.related_report_type}
        return {}

    @staticmethod
    def _build_med_payload(med: Medication, plan: Optional[PlanItem]) -> Dict[str, Any]:
        schedule_template = list(med.schedule_days_template or [])
        schedule_days = (
            list(plan.schedule_days) if plan and plan.schedule_days else schedule_template
        )
        return {
            "library_id": med.id,
            "name": med.name,
            "default_dosage": med.default_dosage,
            "default_frequency": med.default_frequency,
            "schedule_days_template": schedule_template,
            "plan_item_id": plan.id if plan else None,
            "status": plan.status if plan else choices.PlanItemStatus.DISABLED,
            "is_active": bool(plan and plan.status == choices.PlanItemStatus.ACTIVE),
            "schedule_days": schedule_days,
            "current_dosage": plan.drug_dosage if plan else med.default_dosage,
            "current_usage": plan.drug_usage if plan else med.default_frequency,
            "priority_level": plan.priority_level if plan else None,
            "interaction_config": plan.interaction_config if plan else {},
        }

    @staticmethod
    def _build_checkup_payload(chk: CheckupLibrary, plan: Optional[PlanItem]) -> Dict[str, Any]:
        schedule_template = list(chk.schedule_days_template or [])
        schedule_days = (
            list(plan.schedule_days) if plan and plan.schedule_days else schedule_template
        )
        return {
            "library_id": chk.id,
            "name": chk.name,
            "schedule_days_template": schedule_template,
            "related_report_type": chk.related_report_type,
            "plan_item_id": plan.id if plan else None,
            "status": plan.status if plan else choices.PlanItemStatus.DISABLED,
            "is_active": bool(plan and plan.status == choices.PlanItemStatus.ACTIVE),
            "schedule_days": schedule_days,
            "interaction_config": plan.interaction_config if plan else {},
        }

    @staticmethod
    def _build_questionnaire_payload(q: Questionnaire, plan: Optional[PlanItem]) -> Dict[str, Any]:
        schedule_template = list(q.schedule_days_template or [])
        schedule_days = (
            list(plan.schedule_days) if plan and plan.schedule_days else schedule_template
        )
        return {
            "library_id": q.id,
            "name": q.name,
            "schedule_days_template": schedule_template,
            "plan_item_id": plan.id if plan else None,
            "status": plan.status if plan else choices.PlanItemStatus.DISABLED,
            "is_active": bool(plan and plan.status == choices.PlanItemStatus.ACTIVE),
            "schedule_days": schedule_days,
            "interaction_config": plan.interaction_config if plan else {},
        }

    @staticmethod
    def _validate_day(plan: PlanItem, day: int) -> None:
        cycle_days = plan.cycle.cycle_days
        if day < 1 or day > cycle_days:
            raise ValidationError(f"执行日需在 1~{cycle_days} 范围内。")

    @staticmethod
    def _get_current_day_index_for_cycle(cycle: TreatmentCycle) -> int:
        """
        计算当前日期在疗程中的 DayIndex：
        - 若今天早于开始日期，则视为第 1 天（尚未开始，无历史）；
        - 若已超过疗程天数，则返回大于 cycle_days 的值，此时所有天数都视作历史。
        """
        today = date.today()
        delta = (today - cycle.start_date).days + 1
        if delta < 1:
            return 1
        return delta
