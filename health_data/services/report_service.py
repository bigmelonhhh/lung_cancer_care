"""报告上传与归档服务。"""

from __future__ import annotations

from datetime import date
from typing import Iterable, List, Dict, Optional

from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.models import CheckupLibrary
from health_data.models import (
    ClinicalEvent,
    ReportImage,
    ReportUpload,
    UploadSource,
    UploaderRole,
)
from users import choices as user_choices
from users.models import CustomUser, DoctorProfile, PatientProfile


def _resolve_uploader_role(
    uploader: Optional[CustomUser],
    uploader_role: Optional[int],
) -> int:
    """根据账号类型推断上传人角色。"""
    if uploader_role is not None:
        return int(uploader_role)
    if uploader is None:
        return int(UploaderRole.PATIENT)
    mapping = {
        user_choices.UserType.PATIENT: UploaderRole.PATIENT,
        user_choices.UserType.DOCTOR: UploaderRole.DOCTOR,
        user_choices.UserType.ASSISTANT: UploaderRole.ASSISTANT,
        user_choices.UserType.ADMIN: UploaderRole.ADMIN,
    }
    return int(mapping.get(uploader.user_type, UploaderRole.PATIENT))


def _coerce_record_type(value: Optional[int]) -> Optional[int]:
    """校验并转换记录类型枚举。"""
    if value is None:
        return None
    value_int = int(value)
    if value_int not in ReportImage.RecordType.values:
        raise ValidationError("记录类型无效，请选择门诊/住院/复查。")
    return value_int


def _ensure_report_date(value: Optional[date]) -> Optional[date]:
    """确保报告日期类型正确。"""
    if value is None:
        return None
    if not isinstance(value, date):
        raise ValidationError("报告日期必须为日期类型。")
    return value


def _normalize_images(images: Iterable) -> List[Dict[str, object]]:
    """将图片入参统一为字典结构。"""
    normalized: List[Dict[str, object]] = []
    for item in images:
        if isinstance(item, str):
            normalized.append({"image_url": item})
            continue
        if isinstance(item, dict) and item.get("image_url"):
            normalized.append(item)
            continue
        raise ValidationError("图片列表必须包含 image_url 字段。")
    return normalized


class ReportUploadService:
    """报告上传服务，负责上传批次与图片明细的创建/删除。"""

    @staticmethod
    def create_upload(
        patient: PatientProfile,
        images: Iterable,
        uploader: Optional[CustomUser] = None,
        upload_source: int = UploadSource.PERSONAL_CENTER,
        uploader_role: Optional[int] = None,
        related_task=None,
    ) -> ReportUpload:
        """
        【功能说明】
        - 创建上传批次并写入图片明细。

        【使用方法】
        - ReportUploadService.create_upload(patient, images, uploader=user)
        - 示例：包含 record_type
          >>> from datetime import date
          >>> from health_data.models import ReportImage, UploadSource
          >>> upload = ReportUploadService.create_upload(
          ...     patient=patient,
          ...     images=[
          ...         {
          ...             "image_url": "https://example.com/report-a.jpg",
          ...             "record_type": ReportImage.RecordType.CHECKUP,
          ...             "report_date": date(2025, 1, 18),
          ...             "checkup_item_id": 12,
          ...         },
          ...         {
          ...             "image_url": "https://example.com/report-b.jpg",
          ...             "record_type": ReportImage.RecordType.OUTPATIENT,
          ...             "report_date": date(2025, 1, 18),
          ...         },
          ...     ],
          ...     uploader=user,
          ...     upload_source=UploadSource.PERSONAL_CENTER,
          ... )
        - 示例：不包含 record_type（类型未知）
          >>> from health_data.models import UploadSource
          >>> upload = ReportUploadService.create_upload(
          ...     patient=patient,
          ...     images=[
          ...         "https://example.com/unknown-1.jpg",
          ...         {"image_url": "https://example.com/unknown-2.jpg"},
          ...     ],
          ...     uploader=user,
          ...     upload_source=UploadSource.PERSONAL_CENTER,
          ... )

        【参数说明】
        - patient: PatientProfile，患者档案。
        - images: 可迭代对象，元素为 image_url 或包含 image_url 的 dict。
        - uploader: CustomUser，上传人账号。
        - upload_source: UploadSource 枚举值。
        - uploader_role: UploaderRole 枚举值，不传则自动推断。
        - related_task: DailyTask，可空。

        【返回值说明】
        - ReportUpload：创建完成的上传批次对象。
        """
        normalized_images = _normalize_images(images)
        if not normalized_images:
            raise ValidationError("至少上传一张图片。")

        resolved_role = _resolve_uploader_role(uploader, uploader_role)

        with transaction.atomic():
            upload = ReportUpload.objects.create(
                patient=patient,
                upload_source=upload_source,
                uploader=uploader,
                uploader_role=resolved_role,
                related_task=related_task,
            )

            image_instances: List[ReportImage] = []
            for payload in normalized_images:
                record_type = _coerce_record_type(payload.get("record_type"))
                report_date = _ensure_report_date(payload.get("report_date"))
                checkup_item = payload.get("checkup_item") or payload.get("checkup_item_id")

                if record_type == ReportImage.RecordType.CHECKUP and not checkup_item:
                    raise ValidationError("复查图片必须指定复查项目。")
                if record_type != ReportImage.RecordType.CHECKUP and checkup_item:
                    raise ValidationError("非复查类型不允许指定复查项目。")

                if isinstance(checkup_item, int):
                    checkup_item = CheckupLibrary.objects.filter(id=checkup_item).first()
                    if checkup_item is None:
                        raise ValidationError("复查项目不存在。")

                image_instances.append(
                    ReportImage(
                        upload=upload,
                        image_url=payload["image_url"],
                        record_type=record_type,
                        checkup_item=checkup_item,
                        report_date=report_date,
                    )
                )

            ReportImage.objects.bulk_create(image_instances)
            return upload

    @staticmethod
    def list_uploads(
        patient: PatientProfile,
        include_deleted: bool = False,
        upload_source: Optional[int] = None,
        upload_sources: Optional[Iterable[int]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        page: int = 1,
        page_size: int = 10,
    ):
        """
        【功能说明】
        - 获取上传批次列表，支持按日期与入口过滤，并分页返回。

        【参数说明】
        - patient: PatientProfile。
        - include_deleted: 是否包含已删除记录。
        - upload_source: UploadSource 枚举值，可空。
        - upload_sources: UploadSource 枚举值集合，可空；优先级高于 upload_source。
        - start_date/end_date: 日期范围，可空。
        - page: 页码，从 1 开始。
        - page_size: 每页数量，默认 10。

        【返回值说明】
        - Django Page 对象，page.object_list 为当前页上传批次列表。
        """
        import logging

        logger = logging.getLogger(__name__)
        logger.info(
            "ReportUploadService.list_uploads patient_id=%s upload_source=%s upload_sources=%s start_date=%s end_date=%s page=%s page_size=%s include_deleted=%s",
            patient.id,
            upload_source,
            list(upload_sources) if upload_sources else None,
            start_date,
            end_date,
            page,
            page_size,
            include_deleted,
        )
        queryset = ReportUpload.objects.filter(patient=patient)
        if not include_deleted:
            queryset = queryset.filter(deleted_at__isnull=True)
        if upload_sources:
            queryset = queryset.filter(upload_source__in=list(upload_sources))
        elif upload_source is not None:
            queryset = queryset.filter(upload_source=upload_source)
        if start_date is not None:
            queryset = queryset.filter(created_at__date__gte=start_date)
        if end_date is not None:
            queryset = queryset.filter(created_at__date__lte=end_date)
        logger.info("ReportUploadService.list_uploads queryset_count=%s", queryset.count())
        paginator = Paginator(queryset.order_by("-created_at"), page_size)
        return paginator.get_page(page)

    @staticmethod
    def delete_upload(upload: ReportUpload) -> bool:
        """
        【功能说明】
        - 删除上传记录；若包含已归档图片，仅标记 deleted_at。

        【返回值说明】
        - bool：True 表示物理删除，False 表示软删除。
        """
        with transaction.atomic():
            archived_exists = upload.images.filter(clinical_event__isnull=False).exists()
            if archived_exists:
                upload.deleted_at = timezone.now()
                upload.save(update_fields=["deleted_at"])
                return False
            upload.delete()
            return True


class ReportArchiveService:
    """报告归档服务，负责图片归档与诊疗记录管理。"""

    @staticmethod
    def list_clinical_events(
        patient: PatientProfile,
        record_type: Optional[str] = None,
        report_start_date: Optional[date] = None,
        report_end_date: Optional[date] = None,
        archive_start_date: Optional[date] = None,
        archive_end_date: Optional[date] = None,
        archiver_name: Optional[str] = None,
        page: int = 1,
        page_size: int = 10,
    ):
        """
        【功能说明】
        - 获取诊疗记录列表，支持多条件过滤并分页。

        【参数说明】
        - patient: PatientProfile。
        - record_type: 记录类型（全部/门诊/住院/复查），可空。
        - report_start_date/report_end_date: 报告日期范围（event_date），可空。
        - archive_start_date/archive_end_date: 归档日期范围（created_at 日期部分），可空。
        - archiver_name: 归档人姓名模糊匹配（医生姓名/用户名），可空。
        - page: 页码，从 1 开始。
        - page_size: 每页数量，默认 10。

        【返回值说明】
        - Django Page 对象，page.object_list 为当前页 ClinicalEvent 列表。
        """
        queryset = ClinicalEvent.objects.filter(patient=patient).select_related(
            "patient",
            "created_by_doctor",
            "created_by_doctor__user",
        )

        normalized_record_type = (record_type or "").strip()
        if normalized_record_type and normalized_record_type not in ("全部", "all"):
            type_map = {
                "门诊": int(ReportImage.RecordType.OUTPATIENT),
                "住院": int(ReportImage.RecordType.INPATIENT),
                "复查": int(ReportImage.RecordType.CHECKUP),
            }
            event_type = type_map.get(normalized_record_type)
            if event_type is not None:
                queryset = queryset.filter(event_type=event_type)

        if report_start_date is not None:
            queryset = queryset.filter(event_date__gte=report_start_date)
        if report_end_date is not None:
            queryset = queryset.filter(event_date__lte=report_end_date)

        if archive_start_date is not None:
            queryset = queryset.filter(created_at__date__gte=archive_start_date)
        if archive_end_date is not None:
            queryset = queryset.filter(created_at__date__lte=archive_end_date)

        normalized_archiver_name = (archiver_name or "").strip()
        if normalized_archiver_name:
            queryset = queryset.filter(
                Q(archiver_name__icontains=normalized_archiver_name)
                | Q(created_by_doctor__name__icontains=normalized_archiver_name)
                | Q(created_by_doctor__user__username__icontains=normalized_archiver_name)
            )

        paginator = Paginator(queryset.order_by("-event_date", "-created_at"), page_size)
        return paginator.get_page(page)

    @staticmethod
    def create_clinical_event(
        patient: PatientProfile,
        event_type: int,
        event_date: date,
        created_by_doctor: Optional[DoctorProfile] = None,
        hospital_name: str = "",
        department_name: str = "",
        interpretation: str = "",
        archiver_name: str = "",
    ) -> ClinicalEvent:
        """
        【功能说明】
        - 创建诊疗记录；若已存在同类记录则补全空字段。
        """
        event_type = _coerce_record_type(event_type)
        if event_type is None:
            raise ValidationError("诊疗记录类型不能为空。")
        event_date = _ensure_report_date(event_date)
        if event_date is None:
            raise ValidationError("诊疗记录日期不能为空。")

        queryset = ClinicalEvent.objects.filter(
            patient=patient,
            event_type=event_type,
            event_date=event_date,
        )
        event = queryset.order_by("-created_at", "-id").first()
        created = False
        if event is None:
            normalized_archiver_name = (archiver_name or "").strip()[:50] or "未知"
            event = ClinicalEvent.objects.create(
                patient=patient,
                event_type=event_type,
                event_date=event_date,
                hospital_name=hospital_name,
                department_name=department_name,
                interpretation=interpretation,
                created_by_doctor=created_by_doctor,
                archiver_name=normalized_archiver_name,
            )
            created = True

        if not created:
            updates = {}
            if hospital_name and not event.hospital_name:
                updates["hospital_name"] = hospital_name
            if department_name and not event.department_name:
                updates["department_name"] = department_name
            if interpretation and not event.interpretation:
                updates["interpretation"] = interpretation
            if created_by_doctor and event.created_by_doctor is None:
                updates["created_by_doctor"] = created_by_doctor
            normalized_archiver_name = (archiver_name or "").strip()[:50]
            if normalized_archiver_name and normalized_archiver_name != event.archiver_name:
                updates["archiver_name"] = normalized_archiver_name
            if updates:
                for key, value in updates.items():
                    setattr(event, key, value)
                event.save(update_fields=list(updates.keys()))

        return event

    @staticmethod
    def update_clinical_event(
        event: ClinicalEvent,
        hospital_name: Optional[str] = None,
        department_name: Optional[str] = None,
        interpretation: Optional[str] = None,
    ) -> ClinicalEvent:
        """
        【功能说明】
        - 更新诊疗记录信息（医院/科室/解读）。
        """
        updates = {}
        if hospital_name is not None:
            updates["hospital_name"] = hospital_name
        if department_name is not None:
            updates["department_name"] = department_name
        if interpretation is not None:
            updates["interpretation"] = interpretation
        if updates:
            for key, value in updates.items():
                setattr(event, key, value)
            event.save(update_fields=list(updates.keys()))
        return event

    @staticmethod
    def archive_images(
        archiver: DoctorProfile,
        updates: Iterable[Dict[str, object]],
        archiver_name: Optional[str] = None,
    ) -> int:
        """
        【功能说明】
        - 批量归档图片，自动绑定或创建诊疗记录。
        """
        updates = list(updates)
        if not updates:
            raise ValidationError("归档更新不能为空。")

        normalized_archiver_name = (archiver_name or "").strip()
        if not normalized_archiver_name:
            normalized_archiver_name = (getattr(archiver, "name", None) or "").strip()
        normalized_archiver_name = normalized_archiver_name[:50] or "未知"

        image_ids = [item.get("image_id") for item in updates if item.get("image_id")]
        if not image_ids:
            raise ValidationError("归档更新缺少 image_id。")

        images = (
            ReportImage.objects.select_related("upload__patient")
            .filter(id__in=image_ids)
        )
        image_map = {img.id: img for img in images}
        if len(image_map) != len(image_ids):
            raise ValidationError("存在无效的图片 ID。")

        checkup_item_ids = {
            item.get("checkup_item_id")
            for item in updates
            if item.get("checkup_item_id")
        }
        checkup_items = CheckupLibrary.objects.in_bulk(checkup_item_ids)

        now = timezone.now()
        images_to_update: List[ReportImage] = []
        event_cache: Dict[tuple, ClinicalEvent] = {}

        for payload in updates:
            raw_image_id = payload.get("image_id")
            if not raw_image_id:
                continue

            try:
                image_id = int(raw_image_id)
            except (ValueError, TypeError):
                raise ValidationError(f"无效的图片ID: {raw_image_id}")

            if image_id not in image_map:
                # 理论上前面的校验已覆盖，但为了健壮性
                continue

            record_type = _coerce_record_type(payload.get("record_type"))
            report_date = _ensure_report_date(payload.get("report_date"))
            checkup_item_id = payload.get("checkup_item_id")

            if record_type is None or report_date is None:
                raise ValidationError("归档必须包含记录类型与报告日期。")
            if record_type == ReportImage.RecordType.CHECKUP and not checkup_item_id:
                raise ValidationError("复查类型必须选择复查项目。")
            if record_type != ReportImage.RecordType.CHECKUP and checkup_item_id:
                raise ValidationError("非复查类型不允许选择复查项目。")

            checkup_item = None
            if checkup_item_id:
                checkup_item = checkup_items.get(checkup_item_id)
                if checkup_item is None:
                    raise ValidationError("复查项目不存在。")

            image = image_map[image_id]
            patient = image.upload.patient
            event_key = (patient.id, record_type, report_date)
            if event_key not in event_cache:
                event_cache[event_key] = ReportArchiveService.create_clinical_event(
                    patient=patient,
                    event_type=record_type,
                    event_date=report_date,
                    created_by_doctor=archiver,
                    archiver_name=normalized_archiver_name,
                )

            image.record_type = record_type
            image.checkup_item = checkup_item
            image.report_date = report_date
            image.clinical_event = event_cache[event_key]
            image.archived_by = archiver
            image.archived_at = now
            images_to_update.append(image)

        ReportImage.objects.bulk_update(
            images_to_update,
            [
                "record_type",
                "checkup_item",
                "report_date",
                "clinical_event",
                "archived_by",
                "archived_at",
            ],
        )
        return len(images_to_update)

    @staticmethod
    def create_record_with_images(
        patient: PatientProfile,
        created_by_doctor: DoctorProfile,
        event_type: int,
        event_date: date,
        images: Iterable,
        hospital_name: str = "",
        department_name: str = "",
        interpretation: str = "",
        uploader: Optional[CustomUser] = None,
    ) -> ClinicalEvent:
        """
        【功能说明】
        - 医生端新增诊疗记录：创建诊疗记录 + 上传批次 + 图片归档。
        """
        normalized_images = _normalize_images(images)
        if not normalized_images:
            raise ValidationError("至少上传一张图片。")

        event_type = _coerce_record_type(event_type)
        if event_type is None:
            raise ValidationError("诊疗记录类型不能为空。")
        event_date = _ensure_report_date(event_date)
        if event_date is None:
            raise ValidationError("诊疗记录日期不能为空。")

        with transaction.atomic():
            resolved_role = _resolve_uploader_role(uploader, None)
            if uploader is None:
                resolved_role = int(UploaderRole.DOCTOR)
            archiver_name = "未知"
            if uploader is not None:
                try:
                    if uploader.user_type == user_choices.UserType.DOCTOR and hasattr(uploader, "doctor_profile"):
                        archiver_name = uploader.doctor_profile.name
                    elif uploader.user_type == user_choices.UserType.ASSISTANT and hasattr(uploader, "assistant_profile"):
                        archiver_name = uploader.assistant_profile.name
                    elif uploader.user_type == user_choices.UserType.SALES and hasattr(uploader, "sales_profile"):
                        archiver_name = uploader.sales_profile.name
                    elif uploader.user_type == user_choices.UserType.PATIENT and hasattr(uploader, "patient_profile"):
                        archiver_name = uploader.patient_profile.name
                    else:
                        archiver_name = uploader.wx_nickname or uploader.username or "未知"
                except Exception:
                    archiver_name = uploader.wx_nickname or uploader.username or "未知"
            elif created_by_doctor is not None:
                archiver_name = created_by_doctor.name or "未知"
            upload = ReportUpload.objects.create(
                patient=patient,
                upload_source=UploadSource.DOCTOR_BACKEND,
                uploader=uploader,
                uploader_role=resolved_role,
            )
            event = ClinicalEvent.objects.create(
                patient=patient,
                event_type=event_type,
                event_date=event_date,
                hospital_name=hospital_name,
                department_name=department_name,
                interpretation=interpretation,
                created_by_doctor=created_by_doctor,
                archiver_name=archiver_name,
            )

            image_instances: List[ReportImage] = []
            now = timezone.now()
            for payload in normalized_images:
                checkup_item = payload.get("checkup_item") or payload.get("checkup_item_id")
                if event_type == ReportImage.RecordType.CHECKUP and not checkup_item:
                    raise ValidationError("复查类型必须选择复查项目。")
                if event_type != ReportImage.RecordType.CHECKUP and checkup_item:
                    raise ValidationError("非复查类型不允许选择复查项目。")

                if isinstance(checkup_item, int):
                    checkup_item = CheckupLibrary.objects.filter(id=checkup_item).first()
                    if checkup_item is None:
                        raise ValidationError("复查项目不存在。")

                image_instances.append(
                    ReportImage(
                        upload=upload,
                        image_url=payload["image_url"],
                        record_type=event_type,
                        checkup_item=checkup_item,
                        report_date=event_date,
                        clinical_event=event,
                        archived_by=created_by_doctor,
                        archived_at=now,
                    )
                )

            ReportImage.objects.bulk_create(image_instances)
            return event

    @staticmethod
    def delete_clinical_event(event: ClinicalEvent) -> int:
        """
        【功能说明】
        - 删除诊疗记录，并清理关联图片归档信息。
        """
        with transaction.atomic():
            updated_count = event.report_images.update(
                record_type=None,
                checkup_item=None,
                report_date=None,
                clinical_event=None,
                archived_by=None,
                archived_at=None,
            )
            event.delete()
            return updated_count
