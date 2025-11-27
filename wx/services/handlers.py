from urllib.parse import quote

from django.conf import settings
from django.urls import reverse
from wechatpy.replies import TextReply

from .reply_rules import REPLY_RULES, DEFAULT_REPLY
from .client import wechat_client, WX_APPID
from users.services.auth import AuthService
from users.services.patient import PatientService
import logging

auth_service = AuthService()
patient_service = PatientService()


def _build_bind_link(profile_id: int) -> str:
    base_url = getattr(settings, "WEB_BASE_URL", "").rstrip("/")
    if not base_url:
        raise RuntimeError("请在环境变量中配置 WEB_BASE_URL")
    path = reverse("web_patient:bind_landing", args=[profile_id])
    redirect_uri = quote(f"{base_url}{path}", safe="")
    return (
        "https://open.weixin.qq.com/connect/oauth2/authorize"
        f"?appid={WX_APPID}&redirect_uri={redirect_uri}"
        "&response_type=code&scope=snsapi_base"
        f"&state={profile_id}#wechat_redirect"
    )


def _bind_prompt(profile_id: int) -> str:
    url = _build_bind_link(profile_id)
    return f"您正在申请绑定患者档案，👉 <a href=\"{url}\">点击此处确认身份</a>"


def _get_event_key(message):
    """兼容 wechatpy 不同事件类的字段命名。"""

    return (
        getattr(message, "event_key", None)
        or getattr(message, "key", None)
        or getattr(message, "scene_id", None)
    )

def handle_message(message):
    """
    微信消息入口
    将微信推送的消息转为业务回复。

    作用：统一管理各类事件/消息的响应策略。
    使用场景：wechat_main 解密出 message 后调用，返回 TextReply 或 None。
    """

    user_openid = message.source
    logging.info(message)
    

    # ---------------------------
    # 1. 关注事件 (Subscribe)
    # ---------------------------
    if message.type == 'event' and message.event == 'subscribe':
        # 获取用户详情（昵称头像）- 可选，如果不急可以异步做
        user_info = wechat_client.user.get(user_openid) 
        user, created = auth_service.get_or_create_wechat_user(user_openid, user_info)
        
        reply_content = "欢迎关注！"
        
        # 处理：关注时可能带有参数（扫码关注）
        # 格式通常是 qrscene_bind_patient_123
        event_key = _get_event_key(message)
        if event_key and str(event_key).startswith('qrscene_bind_patient_'):
            try:
                profile_id = int(str(event_key).split('_')[-1])
                reply_content += "\n" + _bind_prompt(profile_id)
            except Exception as e:
                reply_content += f"\n暂时无法生成绑定链接：{str(e)}"

        return TextReply(content=reply_content, message=message)

    # ---------------------------
    # 2. 扫码事件 (SCAN - 已关注用户扫码)
    # ---------------------------
    if message.type == 'event' and message.event == 'scan':
        # 确保用户存在（理论上已关注必定存在，但防万一）
        auth_service.get_or_create_wechat_user(user_openid)
        
        # 格式通常是 bind_patient_123 (没有 qrscene_ 前缀)
        event_key = _get_event_key(message)
        if event_key and str(event_key).startswith('bind_patient_'):
            try:
                profile_id = int(str(event_key).split('_')[-1])
                return TextReply(content=_bind_prompt(profile_id), message=message)
            except Exception as e:
                return TextReply(content=f"暂时无法生成绑定链接：{str(e)}", message=message)

    # ---------------------------
    # 3. 取消关注
    # ---------------------------
    if message.type == 'event' and message.event == 'unsubscribe':
        auth_service.unsubscribe_user(user_openid)
        return None # 取消关注无法回复

    if message.type == "text":
        keyword = (message.content or "").strip()
        reply = REPLY_RULES.get(keyword, DEFAULT_REPLY)
        return TextReply(content=reply, message=message)
    return None
