from django.db import models


class Medication(models.Model):
    """
    【业务说明】药物知识库表，承载通用名、商品名及默认剂量等基础信息，用于患者用药计划选择。
    【用法】通过后台 Admin 手工维护，患者前台录入时仅做下拉选择，不直接修改。
    """

    class DrugType(models.IntegerChoices):
        TARGETED = 1, "靶向治疗"
        CHEMO = 2, "化疗"
        IMMUNO = 3, "免疫治疗"
        ANTI_VEGF = 4, "合并用药"
        OTHER = 9, "其它"

    class Method(models.IntegerChoices):
        ORAL = 1, "口服"
        IV = 2, "静脉注射"
        OTHER = 9, "其它"

    name = models.CharField(
        "通用名",
        max_length=50,
        unique=True,
        help_text="【说明】药物通用名，例如“奥希替尼”；【约束】唯一。",
    )
    trade_names = models.CharField(
        "商品名",
        max_length=100,
        blank=True,
        help_text="【说明】常见商品名，可录入多个，以空格或顿号分隔，例如“泰瑞沙”；【约束】可空。",
    )
    name_abbr = models.CharField(
        "通用名拼音简码",
        max_length=50,
        blank=True,
        help_text="【说明】通用名拼音首字母缩写，例如“奥希替尼”→“AXTN”；【用法】留空时保存会自动生成。",
    )
    trade_names_abbr = models.CharField(
        "商品名拼音简码",
        max_length=50,
        blank=True,
        help_text="【说明】商品名拼音首字母缩写，例如“泰瑞沙”→“TRS”；【用法】留空时保存会自动生成。",
    )

    drug_type = models.PositiveSmallIntegerField(
        "药物类型",
        choices=DrugType.choices,
        default=DrugType.TARGETED,
        help_text="【说明】靶向/化疗/免疫/抗血管/其它。",
    )
    method = models.PositiveSmallIntegerField(
        "给药方式",
        choices=Method.choices,
        default=Method.ORAL,
        help_text="【说明】口服/静脉/其它。",
    )

    target_gene = models.CharField(
        "靶点",
        max_length=50,
        blank=True,
        help_text="【说明】主要靶点，例如 EGFR、ALK；【约束】可空。",
    )
    default_dosage = models.CharField(
        "默认剂量",
        max_length=50,
        blank=True,
        help_text="【说明】推荐剂量描述，例如“80mg”；【约束】仅作展示。",
    )
    default_frequency = models.CharField(
        "默认频次",
        max_length=50,
        blank=True,
        help_text="【说明】推荐给药频次，例如“每日 1 次”。",
    )
    schedule_days_template = models.JSONField(
        "推荐执行天(周期内)",
        default=list,
        blank=True,
        help_text="【说明】周期天数模板，例如 [1, 8, 15]；留空表示由医生自定义。",
    )
    description = models.TextField(
        "备注说明",
        blank=True,
        help_text="【说明】补充说明、注意事项等。",
    )
    is_active = models.BooleanField(
        "是否启用",
        default=True,
        help_text="【说明】控制药物是否可在前台选择。",
    )

    class Meta:
        verbose_name = "药物知识库"
        verbose_name_plural = "药物知识库"
        db_table = "core_medication"

    def __str__(self) -> str:
        return self.name

    def _build_abbr(self, text: str) -> str:
        """
        将中文名称转换为拼音首字母大写简码。
        例如：奥希替尼 -> AXTN。
        """

        from xpinyin import Pinyin  # 懒加载，避免在未安装依赖时影响其它模块导入

        text = (text or "").strip()
        if not text:
            return ""
        p = Pinyin()
        # get_initials 会返回每个汉字首字母，例如 "奥希替尼" -> "AXTN"
        initials = p.get_initials(text, "")
        return (initials or "").upper()

    def save(self, *args, **kwargs):
        if self.name and not self.name_abbr:
            self.name_abbr = self._build_abbr(self.name)
        if self.trade_names and not self.trade_names_abbr:
            self.trade_names_abbr = self._build_abbr(self.trade_names)
        super().save(*args, **kwargs)
