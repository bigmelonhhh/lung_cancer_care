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
                "content": "你好，欢迎关注慢病康复管理助手！发送【帮助】查看指令。",
                "vars": "未关注用户第一次关注回复信息",
            },

            {
                "code": "scan_patient_code",
                "title": "扫描患者二维码",
                "content": "您正在申请绑定患者档案，👉 <a href=\"{url}\">点击此处确认身份</a>",
                "vars": "扫描患者二维码，如果是新关注会叠加在关注欢迎语后。{url}=链接",
            },

            {
                "code": "scan_sales_code_patient_nosale",
                "title": "患者扫描销售二维码（有病历无绑定销售）",
                "content": "连接成功！您已连接专属服务顾问【{sales_name}】。",
                "vars": "有病历无绑定销售患者， 扫描销售二维码,情况较少。 {sales_name}=销售名字.",
            },
            {
                "code": "scan_sales_code_patient_sale",
                "title": "患者扫描销售二维码（有病历有绑定销售）",
                "content": "感谢您的关注",
                "vars": "有病历，有绑定销售，再次扫描销售二维码。 情况极少",
            },
            {
                "code": "scan_sales_code_no_patient_no_sale",
                "title": "患者扫描销售二维码（无病历无绑定销售）",
                "content": "您已连接专属服务顾问【{sales_name}】。为了提供更专业的服务，👉 <a href=\"{url}\">点击此处完善康复档案</a>",
                "vars": "无病历，无绑定销售，扫描销售二维码。符合大多数情况。{sales_name}=销售名字，{url}=链接. 新关注用户会叠加欢迎提示词",
            },
            {
                "code": "scan_sales_code_no_patient_sale",
                "title": "患者扫描销售二维码（无病历有绑定销售）",
                "content": "为了提供更专业的服务，👉 <a href=\"{url}\">点击此处完善康复档案</a>",
                "vars": "无病历，有绑定销售，扫描销售二维码。情况较少，当前用户被其它销售开发过。{url}=链接. 新关注用户会叠加欢迎提示词",
            },
        ]


