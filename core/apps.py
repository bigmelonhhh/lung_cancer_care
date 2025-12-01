from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'
    verbose_name='核心支持库'

    def ready(self):
        # Ensure admin modules are imported so registrations happen even when
        # autodiscover isn't triggered (e.g., custom admin sites).
        try:
            import core.admin  # noqa: F401
        except ImportError:
            pass
