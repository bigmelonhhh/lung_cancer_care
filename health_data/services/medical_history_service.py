from django.core.paginator import Paginator
from ..models import MedicalHistory

class MedicalHistoryService:
    """
    病史记录服务层
    负责处理患者病史的新增（更新即新增）和历史记录查询。
    """

    @staticmethod
    def add_medical_history(user, patient, data: dict) -> MedicalHistory:
        """
        新增一条病史记录。

        功能说明:
            每次医生或助理修改病情信息时，不覆盖旧记录，而是插入一条新记录，
            用于完整保留病情变化和修改历史。

        参数:
            user: 操作用户 (CustomUser)，通常是医生或助理。
            patient: 关联的患者 (PatientProfile)。
            data: 病史信息字典，包含 tumor_diagnosis, risk_factors 等字段。

        返回值:
            MedicalHistory: 新创建的病史记录对象。

        示例:
            data = {"tumor_diagnosis": "I期肺腺癌", "genetic_test": "EGFR 19外显子缺失"}
            history = MedicalHistoryService.add_medical_history(user, patient, data)
        """
        # 兼容旧字段名（genetic_testing/surgery_info），并优先使用新字段名。
        genetic_test = data.get('genetic_test')
        if genetic_test is None:
            genetic_test = data.get('genetic_testing')
        surgical_information = data.get('surgical_information')
        if surgical_information is None:
            surgical_information = data.get('surgery_info')

        # 使用 get 方法并提供默认空字符串，防止 KeyError，同时处理 None 值
        history = MedicalHistory(
            patient=patient,
            created_by=user,
            tumor_diagnosis=data.get('tumor_diagnosis') or "",
            risk_factors=data.get('risk_factors') or "",
            clinical_diagnosis=data.get('clinical_diagnosis') or "",
            genetic_test=genetic_test or "",
            past_medical_history=data.get('past_medical_history') or "",
            surgical_information=surgical_information or ""
        )
        history.save()
        return history

    @staticmethod
    def get_medical_history_list(patient, page: int = 1, page_size: int = 10):
        """
        获取患者的病史记录列表，支持分页。

        功能说明:
            按创建时间倒序返回病史记录分页结果（最新在最前）。

        参数:
            patient: 关联的患者 (PatientProfile)。
            page: 页码，从 1 开始。
            page_size: 每页条数。

        返回值:
            Page: Django 分页对象。

        示例:
            page1 = MedicalHistoryService.get_medical_history_list(patient, page=1, page_size=10)
        列表默认按创建时间倒序排列（最新的在最前面）。
        """
        queryset = MedicalHistory.objects.filter(patient=patient).order_by('-created_at')
        paginator = Paginator(queryset, page_size)
        # get_page 会自动处理页码越界（如小于1或大于总页数）的情况
        return paginator.get_page(page)

    @staticmethod
    def get_last_medical_history(patient) -> MedicalHistory | None:
        """
        获取患者最新的一条病史记录。

        功能说明:
            查询并返回该患者最新创建的病史记录；若无记录则返回 None。

        参数:
            patient: 关联的患者 (PatientProfile)。

        返回值:
            MedicalHistory | None: 最新的病史记录对象或 None。

        示例:
            last_history = MedicalHistoryService.get_last_medical_history(patient)
        """
        return (
            MedicalHistory.objects.filter(patient=patient)
            .order_by('-created_at')
            .first()
        )
