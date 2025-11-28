from django.core.management.base import BaseCommand

from wx.models import MessageTemplate
from wx.services import TextTemplateService


class Command(BaseCommand):
    help = "初始化或同步微信文案模板，支持幂等执行。"

    def handle(self, *args, **options):
        templates = TextTemplateService.get_initial_data()
        for item in templates:
            code = item["code"]
            defaults = {
                "title": item["title"],
                "content": item["content"],
                "available_vars": item["vars"],
            }
            template, created = MessageTemplate.objects.get_or_create(
                code=code, defaults=defaults
            )
            if created:
                self.stdout.write(
                    self.style.SUCCESS(f"[创建] {code} => {template.title}")
                )
                continue

            fields_to_update = []
            if template.title != item["title"]:
                template.title = item["title"]
                fields_to_update.append("title")
            if template.available_vars != item["vars"]:
                template.available_vars = item["vars"]
                fields_to_update.append("available_vars")

            if fields_to_update:
                fields_to_update.append("updated_at")
                template.save(update_fields=fields_to_update)
                self.stdout.write(
                    self.style.WARNING(f"[更新] {code} => 元数据同步完成")
                )
            else:
                self.stdout.write(f"[跳过] {code} 数据已最新")
