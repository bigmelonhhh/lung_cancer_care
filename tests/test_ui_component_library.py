from pathlib import Path

from django import forms
from django.conf import settings
from django.template.loader import render_to_string
from django.test import SimpleTestCase


class DemoForm(forms.Form):
    name = forms.CharField(label="姓名", help_text="请输入真实姓名")


class UiComponentLibraryTests(SimpleTestCase):
    def test_privacy_image_component_renders_static_source_with_defaults(self):
        html = render_to_string(
            "components/ui/privacy_image.html",
            {"src": "/media/private-report.jpg"},
        )

        self.assertIn('<button type="button"', html)
        self.assertIn('aria-label="打开原图预览"', html)
        self.assertIn('class="relative w-44 aspect-square max-w-full', html)
        self.assertIn("overflow-hidden rounded-2xl border border-slate-200 bg-slate-100 shadow-sm", html)
        self.assertIn("focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2", html)
        self.assertIn('src="/media/private-report.jpg"', html)
        self.assertNotIn(":src=", html)
        self.assertIn('alt=""', html)
        self.assertIn("h-full w-full scale-[1.03] object-cover blur-[2px]", html)
        self.assertIn("pointer-events-none absolute inset-0 bg-white/10", html)
        self.assertIn(
            "pointer-events-none absolute right-0 top-0 inline-flex items-center gap-1 "
            "rounded-t-lg rounded-bl-lg bg-white px-2 py-1 text-[11px] font-medium "
            "text-blue-600 shadow-sm",
            html,
        )
        self.assertIn('viewBox="0 0 1024 1024"', html)
        self.assertIn("隐私保护", html)

    def test_privacy_image_component_renders_alpine_source_and_overrides(self):
        html = render_to_string(
            "components/ui/privacy_image.html",
            {
                "src": "/media/ignored.jpg",
                "x_src": "msg.image_url",
                "label": "已保护",
                "alt": "检查报告",
                "aria_label": "查看检查报告原图",
                "size_class": "w-52 sm:w-60",
                "extra_class": "privacy-card",
                "attrs": '@click="previewImage(msg.image_url)"',
                "image_attrs": '@load="handleMessageImageLoad(msg)"',
            },
        )

        self.assertIn(':src="msg.image_url"', html)
        self.assertNotIn(' src="', html)
        self.assertIn('aria-label="查看检查报告原图"', html)
        self.assertIn('class="relative w-52 sm:w-60 aspect-square', html)
        self.assertIn("privacy-card", html)
        self.assertIn('@click="previewImage(msg.image_url)"', html)
        self.assertIn('@load="handleMessageImageLoad(msg)"', html)
        self.assertIn('alt="检查报告"', html)
        self.assertIn("已保护", html)

    def test_privacy_image_component_renders_display_only_variant(self):
        html = render_to_string(
            "components/ui/privacy_image.html",
            {
                "src": "/media/private-report.jpg",
                "display_only": True,
                "size_class": "w-full",
                "alt": "待上传的检查报告",
            },
        )

        self.assertIn('<div class="relative w-full aspect-square max-w-full', html)
        self.assertNotIn("<button", html)
        self.assertNotIn('aria-label="打开原图预览"', html)
        self.assertNotIn("focus-visible:ring-2", html)
        self.assertIn('src="/media/private-report.jpg"', html)
        self.assertIn('alt="待上传的检查报告"', html)
        self.assertIn("blur-[2px]", html)
        self.assertIn("bg-white/10", html)
        self.assertIn("隐私保护", html)

    def test_patient_chat_uses_privacy_image_component_for_self_images(self):
        chat_template = (
            Path(settings.BASE_DIR) / "templates/web_patient/consultation_chat.html"
        ).read_text(encoding="utf-8")

        self.assertIn(
            '{% include "components/ui/privacy_image.html" with x_src="msg.image_url"',
            chat_template,
        )
        self.assertIn('attrs=\'@click="previewImage(msg.image_url)"\'', chat_template)
        self.assertIn(
            'image_attrs=\'@load="handleMessageImageLoad(msg)"\'',
            chat_template,
        )
        self.assertIn(
            '<template x-if="msg.content_type === \'image\' && !isSelf(msg)">',
            chat_template,
        )
        self.assertIn(
            '<img :src="msg.image_url" class="max-w-full rounded-lg cursor-pointer"',
            chat_template,
        )

    def test_patient_report_list_uses_interactive_privacy_image_component(self):
        report_list_template = (
            Path(settings.BASE_DIR) / "templates/web_patient/my_report_list.html"
        ).read_text(encoding="utf-8")

        self.assertIn(
            '{% include "components/ui/privacy_image.html" with src=image_url',
            report_list_template,
        )
        self.assertIn('size_class="w-full"', report_list_template)
        self.assertIn(
            'attrs=\'onclick="viewImage(this.children[0].src)"\'',
            report_list_template,
        )
        self.assertIn('id="modal-image"', report_list_template)
        self.assertIn("function viewImage(url)", report_list_template)
        self.assertIn('role="dialog"', report_list_template)
        self.assertIn('aria-modal="true"', report_list_template)
        self.assertIn('aria-label="关闭报告原图预览"', report_list_template)
        self.assertIn('onclick="event.stopPropagation()"', report_list_template)
        self.assertIn("event.key === 'Escape'", report_list_template)

    def test_record_checkup_uses_interactive_privacy_image_preview(self):
        checkup_template = (
            Path(settings.BASE_DIR) / "templates/web_patient/record_checkup.html"
        ).read_text(encoding="utf-8")

        self.assertIn(
            '{% include "components/ui/privacy_image.html" with src=img.url size_class="w-full"',
            checkup_template,
        )
        self.assertNotIn("display_only=True", checkup_template)
        self.assertIn('aria_label="查看已上传复查原图"', checkup_template)
        self.assertIn(
            'attrs=\'onclick="viewImage(this.children[0].src)"\'',
            checkup_template,
        )
        self.assertIn('id="record-checkup-privacy-image-template"', checkup_template)
        self.assertIn('aria_label="查看待上传复查原图"', checkup_template)
        self.assertIn(
            "privacyImageTemplate.content.firstElementChild.cloneNode(true)",
            checkup_template,
        )
        self.assertIn("privacyImage.querySelector('img')", checkup_template)
        self.assertIn("img.src = entry.previewUrl", checkup_template)
        self.assertIn("privacyImage.addEventListener('click', function()", checkup_template)
        self.assertIn("viewImage(img.src);", checkup_template)
        self.assertIn("deleteExistingImage", checkup_template)
        delete_bar_classes = (
            "absolute inset-x-0 bottom-0 z-10 flex h-8 items-center justify-center "
            "rounded-b-2xl bg-slate-700/70 px-2 text-xs font-medium text-white "
            "backdrop-blur-sm transition-colors hover:bg-slate-700/80 "
            "active:bg-slate-800/80"
        )
        self.assertIn(delete_bar_classes, checkup_template)
        self.assertIn("actions.dataset.role = 'upload-actions';", checkup_template)
        self.assertIn("retryButton.textContent = '重试';", checkup_template)
        self.assertIn("deleteButton.textContent = '删除';", checkup_template)
        self.assertNotIn("absolute top-2 left-2 w-5 h-5", checkup_template)
        self.assertIn('aria-label="删除{{ item.name }}图片"', checkup_template)
        self.assertIn("deleteButton.type = 'button';", checkup_template)
        self.assertNotIn("deleteBtn.innerHTML = '<svg", checkup_template)
        self.assertIn('id="checkup-image-modal"', checkup_template)
        self.assertIn('id="checkup-modal-image"', checkup_template)
        self.assertIn("function viewImage(url)", checkup_template)
        self.assertIn("function closeImage()", checkup_template)
        self.assertIn("event.stopPropagation()", checkup_template)

    def test_report_upload_uses_interactive_privacy_image_template(self):
        upload_template = (
            Path(settings.BASE_DIR) / "templates/web_patient/my_report_upload.html"
        ).read_text(encoding="utf-8")

        self.assertIn('id="report-upload-privacy-image-template"', upload_template)
        self.assertIn(
            '{% include "components/ui/privacy_image.html" with src="" size_class="w-full"',
            upload_template,
        )
        self.assertNotIn("display_only=True", upload_template)
        self.assertIn('aria_label="查看待上传报告原图"', upload_template)
        self.assertIn(
            "privacyImageTemplate.content.firstElementChild.cloneNode(true)",
            upload_template,
        )
        self.assertIn("privacyImage.querySelector('img')", upload_template)
        self.assertIn("img.src = entry.previewUrl", upload_template)
        self.assertIn("privacyImage.addEventListener('click', function()", upload_template)
        self.assertIn("viewImage(img.src);", upload_template)
        self.assertIn("wrapper.querySelector('img')", upload_template)
        delete_bar_classes = (
            "absolute inset-x-0 bottom-0 z-10 flex h-8 items-center justify-center "
            "rounded-b-2xl bg-slate-700/70 px-2 text-xs font-medium text-white "
            "backdrop-blur-sm transition-colors hover:bg-slate-700/80 "
            "active:bg-slate-800/80"
        )
        self.assertIn("actions.dataset.role = 'upload-actions';", upload_template)
        self.assertIn("retryButton.textContent = '重试';", upload_template)
        self.assertIn("deleteButton.textContent = '删除';", upload_template)
        self.assertNotIn("absolute top-2 left-2 w-6 h-6", upload_template)
        self.assertIn("删除待上传的报告图片", upload_template)
        self.assertNotIn("deleteBtn.innerHTML = '<svg", upload_template)
        self.assertNotIn('data-role="size"', upload_template)
        self.assertNotIn('data-role="status"', upload_template)
        self.assertNotIn("div.appendChild(badge)", upload_template)
        self.assertNotIn("formatBytes", upload_template)
        self.assertIn("compressionApi.createQueue", upload_template)
        self.assertIn("current.compressedSize = result.outputBytes", upload_template)
        self.assertIn("if (img) img.src = newUrl", upload_template)
        self.assertIn("formData.append('upload_meta'", upload_template)
        self.assertIn('id="image-modal"', upload_template)
        self.assertIn('id="modal-image"', upload_template)
        self.assertIn("function viewImage(url)", upload_template)
        self.assertIn("function closeImage()", upload_template)
        self.assertIn("event.stopPropagation()", upload_template)

    def test_shared_image_compression_exposes_clinical_readability_contract(self):
        compression_script = (
            Path(settings.BASE_DIR) / "static/web_patient/image_compression.js"
        ).read_text(encoding="utf-8")

        self.assertIn('API_VERSION: "clinical-readability-v2"', compression_script)
        self.assertIn("isQueueContract: isQueueContract", compression_script)

        for api_name in (
            "inspectImage",
            "validateSelection",
            "compressOne",
            "createQueue",
        ):
            self.assertIn(f"{api_name}: {api_name}", compression_script)

        for error_code in (
            "invalid_image",
            "too_large",
            "too_many_pixels",
            "timeout",
            "cancelled",
            "library_unavailable",
            "compress_failed",
        ):
            self.assertIn(f'"{error_code}"', compression_script)

        self.assertIn("maxWidthOrHeight: 2560", compression_script)
        self.assertIn("maxSizeMB: 1.5", compression_script)
        self.assertIn("initialQuality: 0.82", compression_script)
        self.assertIn("preserveExif: false", compression_script)
        self.assertIn("libURL: workerLibUrl", compression_script)
        self.assertIn("signal: controller.signal", compression_script)
        self.assertIn("new File([file], normalizedName", compression_script)
        self.assertIn("type: inspection.mimeType", compression_script)
        self.assertIn("outputFile.size > targetBytes", compression_script)
        self.assertNotIn("preScaleToBox", compression_script)
        self.assertNotIn("preScaleTo1080p", compression_script)
        self.assertNotIn("allowOriginal", compression_script)
        self.assertNotIn("jsdelivr", compression_script)

    def test_patient_upload_pages_use_shared_cancellable_compression_queue(self):
        base_dir = Path(settings.BASE_DIR)
        templates = {
            "record_checkup": (
                base_dir / "templates/web_patient/record_checkup.html"
            ).read_text(encoding="utf-8"),
            "my_report_upload": (
                base_dir / "templates/web_patient/my_report_upload.html"
            ).read_text(encoding="utf-8"),
        }

        accepted_types = 'accept=".jpg,.jpeg,.png,image/jpeg,image/png"'
        local_worker_attr = (
            'data-worker-lib-url="{% static '
            "'vendor/browser-image-compression/2.0.2/browser-image-compression.js' %}"
        )
        for template in templates.values():
            self.assertIn(accepted_types, template)
            self.assertIn(local_worker_attr, template)
            self.assertIn("image_compression.js' %}?v=clinical-readability-v2", template)
            self.assertIn("let compressionQueue = null", template)
            self.assertIn("let compressionInitializationError = null", template)
            self.assertIn("compressionApi.API_VERSION === COMPRESSION_API_VERSION", template)
            self.assertIn("compressionApi.isQueueContract(candidateQueue)", template)
            self.assertIn("typeof compressionApi.createQueue === 'function'", template)
            self.assertIn("window.LCCImageCompression.validateSelection", template)
            self.assertIn("compressionApi.createQueue", template)
            self.assertIn("concurrency: 1", template)
            self.assertIn("compressionQueue.cancel", template)
            self.assertIn("compressionQueue.hasPending()", template)
            self.assertIn("selectionValidationChain = Promise.resolve()", template)
            self.assertIn("validationInFlight > 0", template)
            self.assertIn("queued", template)
            self.assertIn("processing", template)
            self.assertIn("ready", template)
            self.assertIn("failed", template)
            self.assertIn("retry", template.lower())
            self.assertIn("处理失败", template)
            self.assertIn("clinical_readability_v2", template)
            self.assertNotIn("const compressQueue = []", template)
            self.assertNotIn("compressActiveCount", template)
            self.assertNotIn("超过500KB", template)
            self.assertNotIn("将使用原图上传", template)

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

    def test_agents_documents_privacy_image_component_contract(self):
        guide = Path(settings.BASE_DIR) / "AGENTS.md"
        content = guide.read_text(encoding="utf-8")

        self.assertIn("`privacy_image.html`", content)
        self.assertIn(
            '{% include "components/ui/privacy_image.html" with src="/media/example.jpg" %}',
            content,
        )
        self.assertIn('x_src="msg.image_url"', content)
        self.assertIn('attrs=\'@click="previewImage(msg.image_url)"\'', content)
        self.assertIn(
            'image_attrs=\'@load="handleMessageImageLoad(msg)"\'',
            content,
        )
        self.assertIn("display_only=True", content)
        self.assertIn("HTML `<template>`", content)
        self.assertIn("attrs 和 image_attrs 仅允许传入开发者编写的可信字面量", content)
        self.assertIn("不得插入用户可控数据", content)
