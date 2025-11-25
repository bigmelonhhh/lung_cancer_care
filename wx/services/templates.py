"""模板消息发送逻辑。"""

from .client import wechat_client


def send_template_message(openid, template_id, data, url=None, mini_program=None):
    """封装模板消息发送。

    作用：向公众号用户发送业务通知（如预约提醒）。
    使用场景：服务层或 Celery 任务在满足条件时调用。
    注意：模板跳转 URL 建议指向我们自己的 OAuth 回调，如
    /wx/auth/redirect?target=REAL_URL，这样后端可静默换取 openid 并识别用户。
    """

    return wechat_client.message.send_template(openid, template_id, data, url=url, miniprogram=mini_program)
