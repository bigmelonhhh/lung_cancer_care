from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET
from django.utils.safestring import mark_safe

from core.models import SystemDocument
import markdown


@require_GET
def document_detail(request: HttpRequest, key: str) -> HttpResponse:
    """
    公共文案/协议展示页，根据 key 渲染对应的 SystemDocument。
    不需要登录，适用于登录前查看用户协议/隐私政策等场景。
    """

    try:
        document = SystemDocument.objects.get(key=key, is_active=True)
    except SystemDocument.DoesNotExist:
        raise Http404("文档不存在")

    html_content = markdown.markdown(document.content or "", extensions=["extra"])

    return render(
        request,
        "web_patient/document_detail.html",
        {
            "document": document,
            "html_content": mark_safe(html_content),
        },
    )

