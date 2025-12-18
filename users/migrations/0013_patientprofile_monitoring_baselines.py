from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0012_remove_patientprofile_device_sn"),
    ]

    operations = [
        migrations.AddField(
            model_name="patientprofile",
            name="baseline_body_temperature",
            field=models.DecimalField(
                blank=True,
                decimal_places=1,
                help_text="【业务说明】患者个体的体温参考基线，用于后续偏离判断；【用法】由医生在管理端配置；【示例】36.5；【参数】decimal；【返回值】decimal",
                max_digits=4,
                null=True,
                verbose_name="体温基线(°C)",
            ),
        ),
        migrations.AddField(
            model_name="patientprofile",
            name="baseline_blood_oxygen",
            field=models.PositiveSmallIntegerField(
                blank=True,
                help_text="【业务说明】患者静息状态下的血氧参考水平；【用法】由医生在管理端配置；【示例】98；【参数】int；【返回值】int",
                null=True,
                verbose_name="血氧基线(%)",
            ),
        ),
        migrations.AddField(
            model_name="patientprofile",
            name="baseline_weight",
            field=models.DecimalField(
                blank=True,
                decimal_places=1,
                help_text="【业务说明】患者目标或稳定体重，用于监测体重波动；【用法】由医生在管理端配置；【示例】68.5；【参数】decimal；【返回值】decimal",
                max_digits=5,
                null=True,
                verbose_name="体重基线(kg)",
            ),
        ),
        migrations.AddField(
            model_name="patientprofile",
            name="baseline_blood_pressure_sbp",
            field=models.PositiveSmallIntegerField(
                blank=True,
                help_text="【业务说明】患者平稳期收缩压参考值；【用法】由医生在管理端配置；【示例】120；【参数】int；【返回值】int",
                null=True,
                verbose_name="血压基线-收缩压",
            ),
        ),
        migrations.AddField(
            model_name="patientprofile",
            name="baseline_blood_pressure_dbp",
            field=models.PositiveSmallIntegerField(
                blank=True,
                help_text="【业务说明】患者平稳期舒张压参考值；【用法】由医生在管理端配置；【示例】80；【参数】int；【返回值】int",
                null=True,
                verbose_name="血压基线-舒张压",
            ),
        ),
        migrations.AddField(
            model_name="patientprofile",
            name="baseline_heart_rate",
            field=models.PositiveSmallIntegerField(
                blank=True,
                help_text="【业务说明】患者静息状态下心率参考值；【用法】由医生在管理端配置；【示例】72；【参数】int；【返回值】int",
                null=True,
                verbose_name="心率基线(bpm)",
            ),
        ),
        migrations.AddField(
            model_name="patientprofile",
            name="baseline_steps",
            field=models.PositiveIntegerField(
                blank=True,
                help_text="【业务说明】患者日常活动步数参考值；【用法】由医生在管理端配置；【示例】6000；【参数】int；【返回值】int",
                null=True,
                verbose_name="步数基线(步)",
            ),
        ),
    ]
