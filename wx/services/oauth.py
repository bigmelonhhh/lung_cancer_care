"""OAuth 相关逻辑。"""
import os

from django.conf import settings
from django.urls import reverse
from wechatpy.oauth import WeChatOAuth

from .client import WX_APPID, WX_APPSECRET


# def get_oauth_url(redirect_uri, scope="snsapi_base", state="STATE"):
#     """生成 OAuth 授权地址。
#     作用：在前端引导用户跳转到微信授权页，授权后微信会携带 code 重定向到 redirect_uri。
#     使用场景：需要静默获取 openid（snsapi_base）或主动拉取用户信息（snsapi_userinfo）时。
#     """
#     return wechat_client.oauth.authorize_url(redirect_uri=redirect_uri, scope=scope, state=state)


def _get_wechat_o_auth_cliet(redirect_uri=None, scope="snsapi_base", state="STATE"):
    if not WX_APPID or not WX_APPSECRET:
        raise ValueError("请确保 .env 中配置了 WX_APPID 和 WX_APPSECRET")            
    return WeChatOAuth(WX_APPID, WX_APPSECRET, redirect_uri, scope, state)


def get_oauth_url(redirect_uri, scope="snsapi_base", state="STATE"):
    """生成 OAuth 授权地址（基础方法）。"""
    oauth_client = _get_wechat_o_auth_cliet(redirect_uri, scope=scope, state=state)
    return oauth_client.authorize_url

def get_user_info(code):
    """根据 code 换取用户信息（基础方法）。"""
    oauth_client = _get_wechat_o_auth_cliet()
    data = oauth_client.fetch_access_token(code)
    return data

# ==========================================
# 👇 新增：封装好的菜单链接生成函数
# ==========================================

def generate_menu_auth_url(
    view_name: str,
    state: str = "menu",
    **kwargs,
) -> str:
    """
    生成用于微信公众号菜单的 OAuth2.0 自动登录链接。

    原理：
    1. 根据 view_name 反向解析出路径 (e.g. /p/dashboard/)
    2. 拼接 WEB_BASE_URL 得到完整回调地址 (e.g. http://domain.com/p/dashboard/)
    3. 调用微信 SDK 生成带 AppID 和回调的授权 URL

    :param view_name: Django 路由名称，例如 'web_patient:dashboard'
    :param state: 微信回调时透传的参数，默认 'menu'
    :param kwargs: 传递给 reverse 的参数 (args 或 kwargs)
    :return: 可直接填入微信后台的 URL
    """

    # 1. 获取并清洗基础域名
    base_url = getattr(settings, "WEB_BASE_URL", "")
    if not base_url:
        # 兜底：如果 settings 没配，尝试直接读 env，或者报错
        base_url = os.getenv("WEB_BASE_URL", "")

    if not base_url:
        raise ValueError("❌ 未配置 WEB_BASE_URL，请在 settings.py 中配置网站根域名。")
        
    base_url = base_url.rstrip("/")  # 去掉末尾可能多余的 /

    # 2. 生成相对路径 (支持带参数的 URL，如 /p/order/1024/)
    try:
        path = reverse(view_name, kwargs=kwargs)
    except Exception as e:
        raise ValueError(f"❌ 路由解析失败: {view_name}. 错误: {str(e)}")

    # 3. 拼接完整回调地址
    full_redirect_uri = f"{base_url}{path}"

    # 4. 生成最终链接 (菜单点击一般用静默授权 snsapi_base)
    # 注意：wechatpy 会自动处理 urlencode
    auth_url = get_oauth_url(full_redirect_uri, scope="snsapi_base", state=state)

    return auth_url
