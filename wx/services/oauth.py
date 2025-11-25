"""OAuth 相关逻辑。"""

from .client import wechat_client


def get_oauth_url(redirect_uri, scope="snsapi_base", state="STATE"):
    """生成 OAuth 授权地址。

    作用：在前端引导用户跳转到微信授权页，授权后微信会携带 code 重定向到 redirect_uri。
    使用场景：需要静默获取 openid（snsapi_base）或主动拉取用户信息（snsapi_userinfo）时。
    """

    return wechat_client.oauth.authorize_url(redirect_uri=redirect_uri, scope=scope, state=state)


def get_user_info(code):
    """根据授权回调携带的 code 换取 openid/access_token。

    作用：完成 OAuth 流程第二步，有了 openid 才能绑定业务账号。
    使用场景：在 OAuth 回调视图中调用，解析微信返回的 code。
    """

    data = wechat_client.oauth.fetch_access_token(code)
    return data
