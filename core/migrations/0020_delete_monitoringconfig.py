from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0019_alter_monitoringconfig_check_freq_days"),
    ]

    operations = [
        migrations.DeleteModel(
            name="MonitoringConfig",
        ),
    ]

