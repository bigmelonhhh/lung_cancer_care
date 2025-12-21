from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0023_planitem_template_id"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="planitem",
            name="interaction_config",
        ),
    ]
