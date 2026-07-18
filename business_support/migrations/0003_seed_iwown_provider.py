from django.db import migrations


def seed_iwown_provider(apps, schema_editor):
    """Register IWOWN as an active device-data provider."""
    DeviceProvider = apps.get_model("business_support", "DeviceProvider")
    DeviceProvider.objects.get_or_create(
        code="IWOWN",
        defaults={
            "name": "IWOWN",
            "is_active": True,
            "description": "埃微智能手表健康数据接入。",
        },
    )


def unseed_iwown_provider(apps, schema_editor):
    """Remove the seeded provider only when no device references it."""
    DeviceProvider = apps.get_model("business_support", "DeviceProvider")
    try:
        provider = DeviceProvider.objects.get(code="IWOWN")
    except DeviceProvider.DoesNotExist:
        return
    if not provider.devices.exists():
        provider.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("business_support", "0002_device_provider"),
    ]

    operations = [
        migrations.RunPython(seed_iwown_provider, unseed_iwown_provider),
    ]
