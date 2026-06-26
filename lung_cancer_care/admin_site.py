"""慢病康复管理平台的自定义后台站点配置。"""

from django.conf import settings
from django.contrib.admin import AdminSite
from django.contrib.admin.apps import AdminConfig
from django.template.response import TemplateResponse
from django.urls import path

from .changelog import get_changelog_page_context


class LungCancerAdminSite(AdminSite):
    site_header = "慢病康复管理系统后台"
    site_title = "慢病康复管理系统"
    index_title = "后台管理首页"
    index_template = "admin/custom_index.html"

    def get_app_list(self, request):
        app_dict = self._build_app_dict(request)
        ordered_list = []
        preferred_order = getattr(settings, "ADMIN_APP_ORDER", [])

        for app_label in preferred_order:
            app_config = app_dict.pop(app_label, None)
            if app_config:
                ordered_list.append(app_config)

        # 其余应用按名称字母序追加，保持体验一致。
        ordered_list.extend(sorted(app_dict.values(), key=lambda app: app["name"].lower()))
        return ordered_list

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path("changelog/", self.admin_view(self.changelog_view), name="changelog"),
        ]
        return custom + urls

    def changelog_view(self, request):
        context = {
            **self.each_context(request),
            **get_changelog_page_context(),
            "title": "更新日志",
        }
        return TemplateResponse(request, "admin/changelog.html", context)


class LungCancerAdminConfig(AdminConfig):
    default_site = "lung_cancer_care.admin_site.LungCancerAdminSite"
