"""微信消息业务分发。"""

from wechatpy.replies import TextReply

from .reply_rules import REPLY_RULES, DEFAULT_REPLY


def handle_message(message):
    """将微信推送的消息转为业务回复。

    作用：统一管理各类事件/消息的响应策略。
    使用场景：wechat_main 解密出 message 后调用，返回 TextReply 或 None。
    """

    if message.type == "event" and message.event == "subscribe":
        return TextReply(content="欢迎关注肺癌院外管理系统，我们将为您提供专业服务！", message=message)

    if message.type == "text":
        keyword = (message.content or "").strip()
        reply = REPLY_RULES.get(keyword, DEFAULT_REPLY)
        return TextReply(content=reply, message=message)

    return None
