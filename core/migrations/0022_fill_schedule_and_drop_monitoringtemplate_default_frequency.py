from django.db import migrations


def fill_schedule_days(apps, schema_editor):
    """
    将 MonitoringTemplate 的默认频率用 schedule_days_template 表达出来：
    - 统一设置为 [1,3,5,...,21]，表示“每2天一次”；
    - 即便之前字段为空，也在这里补齐。
    """
    MonitoringTemplate = apps.get_model("core", "MonitoringTemplate")
    default_schedule = list(range(1, 22, 2))

    for tpl in MonitoringTemplate.objects.all():
        tpl.schedule_days_template = default_schedule
        tpl.save(update_fields=["schedule_days_template"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0021_monitoringtemplate_schedule_days_template"),
    ]

    operations = [
        migrations.RunPython(fill_schedule_days, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="monitoringtemplate",
            name="default_frequency",
        ),
    ]
