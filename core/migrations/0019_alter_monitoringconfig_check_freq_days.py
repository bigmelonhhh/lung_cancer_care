from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0018_monitoring_template_and_defaults"),
    ]

    operations = [
        # MonitoringConfig 已在 0020 中删除，该迁移仅保留以维持迁移顺序占位
        migrations.RunPython(migrations.RunPython.noop, migrations.RunPython.noop),
    ]
