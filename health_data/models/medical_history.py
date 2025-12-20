#-*- coding: utf-8 -*-
"""
健康数据 - 病情（既往病史）
"""
from django.db import models
from django.conf import settings


class MedicalHistory(models.Model):
    """
    患者病情记录。

    该模型用于存储患者在不同时间点的病情快照。每次记录都是一次全量的病情描述，
    用于跟踪病情变化。系统只新增记录，不修改或删除旧记录。
    """
    patient = models.ForeignKey(
        'users.PatientProfile',
        on_delete=models.CASCADE,
        related_name='medical_histories',
        verbose_name="所属患者"
    )
    tumor_diagnosis = models.TextField(
        verbose_name="肿瘤诊断",
        help_text="例如：I期肺腺癌(骨、脑转移)",
        blank=True,
        null=True
    )
    risk_factors = models.TextField(
        verbose_name="危险因素",
        help_text="例如：癌症家族史，吸烟",
        blank=True,
        null=True
    )
    clinical_diagnosis = models.TextField(
        verbose_name="临床诊断",
        help_text="例如：右肺上叶后段恶性肿瘤性病变并远端阻塞性肺炎",
        blank=True,
        null=True
    )
    genetic_test = models.TextField(
        verbose_name="基因检测",
        help_text="例如：EGFR 19外显子缺失",
        blank=True,
        null=True
    )
    past_medical_history = models.TextField(
        verbose_name="既往病史",
        help_text="例如：高血压5年，肺结节10年，I型糖尿病",
        blank=True,
        null=True
    )
    surgical_information = models.TextField(
        verbose_name="手术信息",
        help_text="例如：CT引导下肺穿刺活检术",
        blank=True,
        null=True
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='created_medical_histories',
        verbose_name="创建人",
        help_text="记录该条信息的医生或助理",
        null=True,
        blank=True
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="创建时间"
    )

    class Meta:
        verbose_name = "病情记录"
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.patient.name} 的病情记录 - {self.created_at.strftime('%Y-%m-%d %H:%M')}"

