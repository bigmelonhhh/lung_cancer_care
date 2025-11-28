# wx/services/template.py
import logging
from string import Formatter
from typing import Any, Dict, List

from wx.models import MessageTemplate

logger = logging.getLogger(__name__)


class TextTemplateService:
    """封装文本模板的渲染与初始化数据。"""

    @staticmethod
    def get_render_content(code: str, context: Dict[str, Any] | None = None) -> str:
        """
        根据编码获取文案，并安全地替换变量。

        :param code: 数据库中的模版编码
        :param context: 变量字典，如 {'name': '张三', 'age': 18}
        :return: 渲染后的字符串。如果模版不存在，返回 fallback 或空。
        """

        if context is None:
            context = {}

        template = MessageTemplate.objects.filter(code=code, is_active=True).first()
        if not template:
            logger.error("文案模版缺失: %s", code)
            return f"[系统消息] {code}"

        class SafeFormatter(Formatter):
            def get_value(self, key, args, kwargs):
                if isinstance(key, str):
                    return kwargs.get(key, "{" + key + "}")
                return super().get_value(key, args, kwargs)

        try:
            fmt = SafeFormatter()
            return fmt.format(template.content, **context)
        except Exception as exc:  # pragma: no cover - 容错兜底
            logger.error("文案渲染异常: code=%s, error=%s", code, exc)
            return template.content

    @staticmethod
    def get_initial_data() -> List[Dict[str, str]]:
        """
        返回系统预置的文本模板列表，用于初始化或同步。
        """

        return [
            {
                "code": "subscribe_welcome",
                "title": "关注欢迎语",
                "content": "你好，欢迎关注肺部康复管理助手！发送【帮助】查看指令。",
                "vars": "无",
            },
            {
                "code": "bind_success",
                "title": "绑定成功通知",
                "content": "绑定成功！{name}，您的专属顾问是{sales_name}。",
                "vars": "{name}=用户昵称, {sales_name}=销售姓名",
            },
            {
                "code": "sales_bind_existing",
                "title": "扫码绑定-已有档案",
                "content": "您已绑定专属顾问【{sales_name}】，如有疑问可直接联系。",
                "vars": "{sales_name}=销售姓名",
            },
            {
                "code": "sales_bind_new",
                "title": "扫码绑定-新用户",
                "content": "欢迎咨询！您已连接顾问【{sales_name}】。为了提供更专业的服务，👉 <a href='{url}'>点击此处完善康复档案</a>",
                "vars": "{sales_name}=销售姓名, {url}=H5链接",
            },
        ]


