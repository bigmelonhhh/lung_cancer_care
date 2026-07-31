from django.db import migrations


TEMPLATES = (
    ("M_GLU", "血糖监测", 70),
    ("M_KETONE", "血酮监测", 80),
    ("M_UA", "尿酸监测", 90),
)


def seed_templates(apps, schema_editor):
    MonitoringTemplate = apps.get_model("core", "MonitoringTemplate")
    schedule_days = list(range(1, 22, 2))
    for code, name, sort_order in TEMPLATES:
        MonitoringTemplate.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "metric_type": code,
                "schedule_days_template": schedule_days,
                "is_active": True,
                "sort_order": sort_order,
            },
        )


def remove_templates(apps, schema_editor):
    MonitoringTemplate = apps.get_model("core", "MonitoringTemplate")
    MonitoringTemplate.objects.filter(code__in=[item[0] for item in TEMPLATES]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0032_alter_medication_method"),
    ]

    operations = [
        migrations.RunPython(seed_templates, remove_templates),
    ]
