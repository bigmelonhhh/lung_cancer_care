"""
Auth-related service utilities.
"""

from typing import Optional, Tuple

from django.conf import settings
from django.contrib.auth import authenticate, login

from users import choices
from users.models import CustomUser
from django.db import transaction


class AuthService:
    """统一处理多端登录，账号管理（微信/PC），保证 Session 状态一致。"""

    def __init__(self) -> None:
        backends = getattr(settings, "AUTHENTICATION_BACKENDS", None) or [
            "django.contrib.auth.backends.ModelBackend"
        ]
        self.default_backend = backends[0]

    def _fetch_wechat_openid(self, code: str) -> str:
        """TODO: 调用真实的公众号接口换取 openid。"""

        return f"mock_{code}"

    def wechat_login(self, request, code: str) -> Tuple[bool, Optional[CustomUser]]:
        if not code:
            return False, "缺少 code 参数"

        openid = self._fetch_wechat_openid(code)
        user = CustomUser.objects.filter(wx_openid=openid).first()
        if not user:
            user = CustomUser.objects.create(
                wx_openid=openid,
                wx_nickname="微信用户",
                user_type=choices.UserType.PATIENT,
                is_active=True,
            )
        login(request, user, backend=self.default_backend)
        return True, user

    def pc_login(self, request, username: str, password: str) -> Tuple[bool, Optional[CustomUser]]:
        if not username or not password:
            return False, "请输入用户名和密码"
        user = authenticate(request, username=username, password=password)
        if not user:
            return False, "用户名或密码错误"
        login(request, user)
        return True, user
    
    def get_or_create_wechat_user(self, openid: str, user_info: dict|None = None) -> Tuple[CustomUser, bool]:
        """
        【业务说明】根据 OpenID 获取或创建基础账号。
        【使用场景】微信收到 subscribe 事件或 OAuth 登录时。
        """
        created = False
        user = CustomUser.objects.filter(wx_openid=openid).first()
        
        if not user:
            with transaction.atomic():
                # 创建新用户
                user = CustomUser.objects.create(
                    wx_openid=openid,
                    username=f"wx_{openid[:8]}", # 临时用户名
                    user_type=choices.UserType.PATIENT,
                    is_active=True,
                    is_subscribe=True
                )
                created = True
        
        # 如果有新的用户信息（昵称/头像），更新一下
        if user_info:
            updated = False
            if user_info.get('nickname') and user.wx_nickname != user_info['nickname']:
                user.wx_nickname = user_info['nickname']
                updated = True
            if user_info.get('headimgurl') and user.wx_avatar_url != user_info['headimgurl']:
                user.wx_avatar_url = user_info['headimgurl']
                updated = True
            if not user.is_subscribe: # 重新关注
                user.is_subscribe = True
                updated = True
            
            if updated:
                user.save()

        return user, created

    def unsubscribe_user(self, openid: str):
        """处理取消关注"""
        CustomUser.objects.filter(wx_openid=openid).update(is_subscribe=False)
