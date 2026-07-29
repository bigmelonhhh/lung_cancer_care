from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0020_patientprofile_baseline_height_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="patientprofile",
            name="baseline_blood_glucose",
            field=models.DecimalField(
                blank=True,
                decimal_places=1,
                help_text="患者稳定状态下的血糖参考值，由医生在管理端配置。",
                max_digits=5,
                null=True,
                verbose_name="血糖基线(mmol/L)",
            ),
        ),
        migrations.AddField(
            model_name="patientprofile",
            name="baseline_blood_ketone",
            field=models.DecimalField(
                blank=True,
                decimal_places=1,
                help_text="患者稳定状态下的血酮参考值，由医生在管理端配置。",
                max_digits=4,
                null=True,
                verbose_name="血酮基线(mmol/L)",
            ),
        ),
        migrations.AddField(
            model_name="patientprofile",
            name="baseline_uric_acid",
            field=models.PositiveIntegerField(
                blank=True,
                help_text="患者稳定状态下的尿酸参考值，由医生在管理端配置。",
                null=True,
                verbose_name="尿酸基线(μmol/L)",
            ),
        ),
    ]
