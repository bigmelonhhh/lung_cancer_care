from django.db import migrations, models


def seed_monitoring_templates(apps, schema_editor):
    MonitoringTemplate = apps.get_model("core", "MonitoringTemplate")

    data = [
        {
            "name": "体温监测",
            "code": "M_TEMP",
            "metric_type": "body_temperature",
            "sort_order": 10,
        },
        {
            "name": "血氧监测",
            "code": "M_SPO2",
            "metric_type": "blood_oxygen",
            "sort_order": 20,
        },
        {
            "name": "体重监测",
            "code": "M_WEIGHT",
            "metric_type": "weight",
            "sort_order": 30,
        },
        {
            "name": "血压监测",
            "code": "M_BP",
            "metric_type": "blood_pressure",
            "sort_order": 40,
        },
        {
            "name": "心率监测",
            "code": "M_HR",
            "metric_type": "heart_rate",
            "sort_order": 50,
        },
        {
            "name": "步数监测",
            "code": "M_STEPS",
            "metric_type": "steps",
            "sort_order": 60,
        },
    ]

    for item in data:
        MonitoringTemplate.objects.update_or_create(
            code=item["code"],
            defaults={
                "name": item["name"],
                "metric_type": item["metric_type"],
                "default_frequency": "每2天一次",
                "is_active": True,
                "sort_order": item["sort_order"],
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0017_alter_dailytask_task_type_alter_planitem_category"),
    ]

    operations = [
        migrations.CreateModel(
            name="MonitoringTemplate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=50, verbose_name="监测名称")),
                (
                    "code",
                    models.CharField(
                        help_text="唯一英文编码，例如 M_TEMP、M_SPO2。",
                        max_length=50,
                        unique=True,
                        verbose_name="监测编码",
                    ),
                ),
                (
                    "metric_type",
                    models.CharField(
                        blank=True,
                        help_text="对应 HealthMetric.MetricType，用于将监测结果映射到指标表。",
                        max_length=50,
                        null=True,
                        verbose_name="关联指标类型",
                    ),
                ),
                (
                    "default_frequency",
                    models.CharField(
                        blank=True,
                        help_text="推荐监测频次描述，例如“每2天一次”。",
                        max_length=50,
                        verbose_name="默认频次",
                    ),
                ),
                ("is_active", models.BooleanField(default=True, verbose_name="是否启用")),
                ("sort_order", models.PositiveIntegerField(default=0, verbose_name="排序权重")),
            ],
            options={
                "verbose_name": "监测模板",
                "verbose_name_plural": "监测模板",
                "db_table": "core_monitoring_templates",
                "ordering": ("sort_order", "name"),
            },
        ),
        migrations.RunPython(seed_monitoring_templates, migrations.RunPython.noop),
    ]
