from django.db import models


class MedicalHistory(models.Model):
    """病程/病史快照表。"""

    patient = models.ForeignKey(
        "users.PatientProfile",
        on_delete=models.CASCADE,
        related_name="medical_histories",
        verbose_name="患者",
    )
    record_date = models.DateField("记录日期")
    diagnosis = models.CharField("临床诊断", max_length=100, blank=True)
    pathology = models.CharField("病理类型", max_length=50, blank=True)
    tnm_stage = models.CharField("TNM 分期", max_length=20, blank=True)
    gene_mutation = models.CharField("基因检测结果", max_length=100, blank=True)
    risk_factors = models.TextField("危险因素(JSON)", blank=True)
    doctor_note = models.TextField("阶段小结", blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        db_table = "health_medical_history"
        verbose_name = "病程历史"
        verbose_name_plural = "病程历史"
