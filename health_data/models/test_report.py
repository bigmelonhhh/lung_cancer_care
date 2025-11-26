from django.db import models


class TestReport(models.Model):
    """检查检验报告表。"""

    patient = models.ForeignKey(
        "users.PatientProfile",
        on_delete=models.CASCADE,
        related_name="test_reports",
        verbose_name="患者",
    )
    report_date = models.DateField("检查日期")
    report_type = models.PositiveSmallIntegerField(
        "报告类型",
        choices=[
            (1, "CT"),
            (2, "血常规"),
            (3, "生化"),
            (4, "基因"),
            (5, "处方"),
        ],
        blank=True,
        null=True,
    )
    image_urls = models.JSONField("图片 URL 列表")
    ocr_text = models.TextField("OCR 文本", blank=True)
    interpretation = models.TextField("解读结论", blank=True)
    created_at = models.DateTimeField("上传时间", auto_now_add=True)

    class Meta:
        db_table = "health_test_reports"
        verbose_name = "检查报告"
        verbose_name_plural = "检查报告"
        indexes = [
            models.Index(fields=["patient", "report_date"], name="idx_patient_date"),
        ]
