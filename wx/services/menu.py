from .client import WX_APPID, WX_APPSECRET, wechat_client

def create_menu():
    wechat_client.menu.delete()
    MENU = {
        "button": [
            {
                "type": "view",
                "name": "管理计划",  # 按钮显示名称，自定义
                "url": (
                    "https://open.weixin.qq.com/connect/oauth2/authorize"
                    "?appid=wx3a562cd7118f6fd5"
                    "&redirect_uri=http%3A%2F%2Feric.dagimed.com%2Fp%2Fhome%2F"
                    "&response_type=code"
                    "&scope=snsapi_base"
                    "&state=STATE#wechat_redirect"
                    ),
                },
            {
                "type": "view",
                "name": "个人中心",  # 按钮显示名称，自定义
                "url": (
                    "https://open.weixin.qq.com/connect/oauth2/authorize"
                    "?appid=wx3a562cd7118f6fd5"
                    "&redirect_uri=http%3A%2F%2Feric.dagimed.com%2Fp%2Fdashboard%2F"
                    "&response_type=code"
                    "&scope=snsapi_base"
                    "&state=STATE#wechat_redirect"
                    ),
                }
            ]
        }
    wechat_client.menu.create(MENU)