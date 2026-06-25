from pathlib import Path

from django import forms
from django.conf import settings
from django.template.loader import render_to_string
from django.test import SimpleTestCase


class DemoForm(forms.Form):
    name = forms.CharField(label="姓名", help_text="请输入真实姓名")


class UiComponentLibraryTests(SimpleTestCase):
    def test_core_ui_components_render_with_expected_contracts(self):
        button_html = render_to_string(
            "components/ui/button.html",
            {
                "label": "保存",
                "href": "#save",
                "variant": "primary",
                "size": "md",
                "attrs": 'hx-post="/demo"',
            },
        )
        self.assertIn("<a ", button_html)
        self.assertIn("保存", button_html)
        self.assertIn("bg-blue-600", button_html)
        self.assertIn('hx-post="/demo"', button_html)

        badge_html = render_to_string(
            "components/ui/badge.html",
            {"label": "已完成", "tone": "success"},
        )
        self.assertIn("已完成", badge_html)
        self.assertIn("bg-emerald-50", badge_html)

        alert_html = render_to_string(
            "components/ui/alert.html",
            {"title": "提交失败", "message": "请检查必填项", "tone": "danger"},
        )
        self.assertIn("提交失败", alert_html)
        self.assertIn("请检查必填项", alert_html)
        self.assertIn("border-rose-200", alert_html)

        empty_html = render_to_string(
            "components/ui/empty_state.html",
            {"title": "暂无数据", "description": "当前筛选条件下没有记录。"},
        )
        self.assertIn("暂无数据", empty_html)
        self.assertIn("当前筛选条件下没有记录。", empty_html)
        self.assertIn("border-dashed", empty_html)

        loading_html = render_to_string(
            "components/ui/loading.html",
            {"label": "加载中..."},
        )
        self.assertIn("加载中...", loading_html)
        self.assertIn("animate-spin", loading_html)

        table_empty_html = render_to_string(
            "components/ui/table_empty.html",
            {"message": "暂无记录", "colspan": 4},
        )
        self.assertIn("暂无记录", table_empty_html)
        self.assertIn('colspan="4"', table_empty_html)

    def test_layout_and_form_components_render(self):
        page_header_html = render_to_string(
            "components/ui/page_header.html",
            {
                "title": "患者管理",
                "subtitle": "集中查看随访、指标和待办",
                "action_label": "新增患者",
                "action_href": "#create",
            },
        )
        self.assertIn("患者管理", page_header_html)
        self.assertIn("集中查看随访、指标和待办", page_header_html)
        self.assertIn("新增患者", page_header_html)

        panel_html = render_to_string(
            "components/ui/panel.html",
            {"title": "基础信息", "body": "患者基本档案"},
        )
        self.assertIn("基础信息", panel_html)
        self.assertIn("患者基本档案", panel_html)

        form = DemoForm(data={})
        form.is_valid()
        field_html = render_to_string(
            "components/ui/form_field.html",
            {"field": form["name"]},
        )
        self.assertIn("姓名", field_html)
        self.assertIn("请输入真实姓名", field_html)
        self.assertIn("这个字段是必填项。", field_html)

        modal_html = render_to_string(
            "components/ui/modal.html",
            {
                "modal_id": "demo-modal",
                "title": "确认操作",
                "description": "该操作需要二次确认。",
                "body": "确认后将立即生效。",
                "cancel_label": "取消",
                "confirm_label": "确认",
                "close_on_click": True,
            },
        )
        self.assertIn('id="demo-modal"', modal_html)
        self.assertIn("确认操作", modal_html)
        self.assertIn("确认后将立即生效。", modal_html)
        self.assertIn("取消", modal_html)
        self.assertIn("确认", modal_html)

    def test_agents_documents_ui_component_rules(self):
        guide = Path(settings.BASE_DIR) / "AGENTS.md"
        content = guide.read_text(encoding="utf-8")

        self.assertIn("templates/components/ui/", content)
        self.assertIn("新增页面优先复用项目 UI 组件", content)
        self.assertIn("不引入 AntD、Element Plus", content)
        self.assertIn("不要为了套用组件而改动存量页面", content)
