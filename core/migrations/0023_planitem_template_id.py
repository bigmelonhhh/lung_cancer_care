from django.db import migrations, models


def forwards(apps, schema_editor):
    PlanItem = apps.get_model("core", "PlanItem")

    for item in PlanItem.objects.all():
        template_id = None
        if item.category == 1:
            template_id = item.medicine_id
        elif item.category == 2:
            template_id = item.checkup_id
        elif item.category == 3:
            template_id = item.questionnaire_id
        elif item.category == 4:
            config = item.interaction_config or {}
            if isinstance(config, dict):
                template_id = config.get("monitoring_template_id")

        if template_id is None:
            raise ValueError(f"PlanItem {item.pk} missing template binding.")

        item.template_id = int(template_id)
        item.save(update_fields=["template_id"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0022_fill_schedule_and_drop_monitoringtemplate_default_frequency"),
    ]

    operations = [
        migrations.AddField(
            model_name="planitem",
            name="template_id",
            field=models.PositiveIntegerField(null=True, verbose_name="模板ID"),
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="planitem",
            name="template_id",
            field=models.PositiveIntegerField(verbose_name="模板ID"),
        ),
        migrations.RemoveField(
            model_name="planitem",
            name="medicine",
        ),
        migrations.RemoveField(
            model_name="planitem",
            name="checkup",
        ),
        migrations.RemoveField(
            model_name="planitem",
            name="questionnaire",
        ),
        migrations.AddIndex(
            model_name="planitem",
            index=models.Index(
                fields=["cycle", "category", "template_id"],
                name="idx_cycle_category_template",
            ),
        ),
    ]
