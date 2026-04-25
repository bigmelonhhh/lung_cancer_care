from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0017_customuser_message_preferences"),
    ]

    operations = [
        migrations.AddField(
            model_name="patientprofile",
            name="indicator_preferences",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="【业务说明】保存患者级共享的指标配置；【用法】医生工作台核心关注指标读取；【示例】{'followup_review': {'selected_mapping_ids': [1, 2]}}；【参数】dict；【返回值】dict",
                verbose_name="指标配置偏好",
            ),
        ),
    ]
