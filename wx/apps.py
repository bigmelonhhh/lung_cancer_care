from django.apps import AppConfig


class WxConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wx'
    verbose_name = "微信模块"