from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("health_data", "0026_alter_healthmetric_metric_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="healthmetric",
            name="measurement_context",
            field=models.CharField(
                blank=True,
                choices=[
                    ("fasting", "空腹"),
                    ("postprandial_2h", "餐后2小时"),
                    ("random", "随机"),
                ],
                help_text="血糖手工录入场景；其他指标及兼容旧数据可为空。",
                max_length=32,
                null=True,
                verbose_name="测量场景",
            ),
        ),
    ]
