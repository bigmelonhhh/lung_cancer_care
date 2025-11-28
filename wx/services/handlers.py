from urllib.parse import quote

from django.conf import settings
from django.urls import reverse
from wechatpy.replies import TextReply

from .reply_rules import REPLY_RULES, DEFAULT_REPLY
from .client import wechat_client, WX_APPID
from users.services.auth import AuthService
from users.services.patient import PatientService
from users.services.sales import SalesService
from users.models import SalesProfile
from wx.services.reply_text_template import TextTemplateService
import logging


auth_service = AuthService()
patient_service = PatientService()
sales_service = SalesService()


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
    reply_text = TextTemplateService.get_render_content("scan_patient_code",{url: url})
    return reply_text


def _get_event_key(message):
    """兼容 wechatpy 不同事件类的字段命名。"""

    return (
        getattr(message, "event_key", None)
        or getattr(message, "key", None)
        or getattr(message, "scene_id", None)
    )

def _handle_sales_binding(event_key: str, user):
    """
    根据扫码事件绑定销售。
    支持 qrscene_bind_sales_xxx 或 bind_sales_xxx。
    # TODO 这里需要统一配置话术。
    """

    try:
        sales_id = int(event_key.split("_")[-1])
    except (ValueError, TypeError):
        return "参数错误，无法识别工作人员信息。"

    sale = SalesProfile.objects.select_related("user").filter(pk=sales_id).first()
    if not sale:
        return "未找到对应的顾问人员。"

    sales_name = sale.name or (sale.user.display_name if sale.user else "顾问")

    patient_profile = getattr(user, "patient_profile", None)
    #已有病历的情况
    if patient_profile:
        #有病历，无销售
        if not patient_profile.sales:    
            patient_profile.sales = sale
            patient_profile.save(update_fields=["sales", "updated_at"])
            replay_text = TextTemplateService.get_render_content("scan_sales_code_patient_nosale",{"sales_name": sales_name})
            return replay_text
        #有病历，有销售
        else:
            replay_text = TextTemplateService.get_render_content("scan_sales_code_patient_sale",{"sales_name": sales_name})
            return replay_text


    onboarding_path = reverse("web_patient:onboarding")
    base_url = getattr(settings, "WEB_BASE_URL", "").rstrip("/")
    link = f"{base_url}{onboarding_path}" if base_url else onboarding_path            
    replay_text = ""
    # 无病历，无销售
    if not user.bound_sales:
        user.bound_sales = sale
        user.save(update_fields=["bound_sales", "updated_at"])
        replay_text = TextTemplateService.get_render_content("scan_sales_code_no_patient_no_sale",{"sales_name": sales_name, "url": link})
    #无病历，有销售
    else:
        replay_text = TextTemplateService.get_render_content("scan_sales_code_no_patient_sale",{"url": link})
    return replay_text


def handle_message(message):
    """
    微信消息入口
    将微信推送的消息转为业务回复。

    作用：统一管理各类事件/消息的响应策略。
    使用场景：wechat_main 解密出 message 后调用，返回 TextReply 或 None。
    """

    user_openid = message.source
    print("-----------")
    print(user_openid)
    print("-----------")
    

    # ---------------------------
    # 1. 关注事件 (Subscribe)
    # ---------------------------
    if message.type == 'event' and message.event == 'subscribe':
        # 获取用户详情（昵称头像）
        user_info = wechat_client.user.get(user_openid) 
        user, created = auth_service.get_or_create_wechat_user(user_openid, user_info)
        #获取订阅关注的文本
        subscribe_welcome = TextTemplateService.get_render_content("subscribe_welcome")
        reply_content = subscribe_welcome
        
        # 处理：关注时可能带有参数（扫码关注）
        # 格式通常是 qrscene_bind_patient_123
        event_key = _get_event_key(message)
        if event_key:
            event_str = str(event_key)
            if event_str.startswith('qrscene_bind_patient_'):
                try:
                    profile_id = int(event_str.split('_')[-1])
                    reply_content += "\n" + _bind_prompt(profile_id)
                except Exception as e:
                    reply_content += f"\n暂时无法生成绑定链接：{str(e)}"
            elif event_str.startswith('qrscene_bind_sales_'):
                reply_content += "\n" + _handle_sales_binding(event_str, user)

        return TextReply(content=reply_content, message=message)


    # ---------------------------
    # 2. 扫码事件 (SCAN - 已关注用户扫码)
    # ---------------------------
    if message.type == 'event' and message.event == 'scan':
        # 确保用户存在（理论上已关注必定存在，但防万一）
        user = auth_service.get_or_create_wechat_user(user_openid)[0]
        # 格式通常是 bind_patient_123 (没有 qrscene_ 前缀)
        event_key = _get_event_key(message)
        if event_key:
            event_str = str(event_key)
            #扫描患者二维码进入
            if event_str.startswith('bind_patient_'):
                try:
                    profile_id = int(event_str.split('_')[-1])
                    return TextReply(content=_bind_prompt(profile_id), message=message)
                except Exception as e:
                    return TextReply(content=f"暂时无法生成绑定链接：{str(e)}", message=message)
            #扫销售二维码进入
            if event_str.startswith('bind_sales_'):
                content = _handle_sales_binding(event_str, user)
                return TextReply(content=content, message=message)

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
