import logging
from django.conf import settings
from django.urls import reverse
from django.db import transaction
from wechatpy.replies import TextReply

from .reply_rules import REPLY_RULES, DEFAULT_REPLY
from .client import wechat_client, WX_APPID
from users.services.auth import AuthService
from users.models import SalesProfile, DoctorProfile, PatientProfile
from users import choices
from wx.services.reply_text_template import TextTemplateService
from wx.services.oauth import get_oauth_url, generate_menu_auth_url

logger = logging.getLogger(__name__)
auth_service = AuthService()

# ==========================================
# 1. 辅助函数：统一获取 Event Key
# ==========================================
def _get_event_key(message):
    """兼容关注(qrscene_)和扫码(无前缀)的参数提取"""
    key = getattr(message, "scene_id", None) or getattr(message, "event_key", None) or getattr(message, "key", None) 
    if not key:
        return None
    # 移除关注事件的前缀
    return str(key).replace("qrscene_", "")

# def _get_full_url(path_name, **kwargs):
#     """辅助生成带域名的完整 URL"""
#     base_url = getattr(settings, "WEB_BASE_URL", "").rstrip("/")
#     path = reverse(path_name, kwargs=kwargs)
#     return f"{base_url}{path}"

# ==========================================
# 2. 具体业务处理器 (Handlers)
# ==========================================

def _handle_sales_scan(user, object_id):
    """处理扫描销售码逻辑"""
    sale = SalesProfile.objects.select_related("user").filter(pk=object_id).first()
    if not sale:
        return "未找到对应的顾问人员信息。"
    
    sales_name = sale.name
    patient_profile = getattr(user, "patient_profile", None)

    # 场景 A: 已有病历 (患者)
    if patient_profile:
        if not patient_profile.sales:
            # 补录销售
            patient_profile.sales = sale
            patient_profile.save(update_fields=["sales", "updated_at"])
            return TextTemplateService.get_render_content("scan_sales_code_patient_nosale", {"sales_name": sales_name})
        else:
            # 已有销售，不抢单，仅问候
            return TextTemplateService.get_render_content("scan_sales_code_patient_sale", {"sales_name": sales_name})

    # 场景 B: 无病历 (白户/潜客)
    # 生成建档链接
    link = generate_menu_auth_url("web_patient:onboarding",state=f"sales_{object_id}")
    # link = get_oauth_url(redirect_uri=link, state=f"sales_{object_id}")
    
    if not user.bound_sales:
        # 锁定潜客归属
        user.bound_sales = sale
        user.save(update_fields=["bound_sales", "updated_at"])
        return TextTemplateService.get_render_content("scan_sales_code_no_patient_no_sale", {"sales_name": sales_name, "url": link})
    else:
        # 已有潜客归属，不改归属，仅推送链接
        return TextTemplateService.get_render_content("scan_sales_code_no_patient_sale", {"url": link})

def _handle_patient_scan(user, object_id):
    """处理扫描患者档案码逻辑 (绑定家属/本人)"""
    # 简单的生成链接逻辑
    # full_redirect_uri = _get_full_url()
    # url = get_oauth_url(redirect_uri=full_redirect_uri, state=str(object_id))
    url = generate_menu_auth_url("web_patient:bind_landing", patient_id=object_id)
    return TextTemplateService.get_render_content("scan_patient_code", {"url": url})

# ==========================================
# 3. 策略分发配置
# ==========================================
# 格式: '前缀': 处理函数
QR_HANDLERS = {
    'bind_sales': _handle_sales_scan,
    'bind_patient': _handle_patient_scan,
    # 'qrscene_bind_sales': ... 如果不想在提取时 replace，也可以在这里穷举
}

# ==========================================
# 4. 主入口
# ==========================================
def handle_message(message):
    user_openid = message.source
    
    # 1. 统一处理关注/扫码事件
    if message.type == 'event':
        if message.event in ['subscribe', 'subscribe_scan']:
            # 获取并更新用户信息
            user_info = wechat_client.user.get(user_openid)
            user, created = auth_service.get_or_create_wechat_user(user_openid, user_info)
            
            reply_content = TextTemplateService.get_render_content("subscribe_welcome")
            
            # 检查是否有参数（扫码关注）
            event_key = _get_event_key(message)
            if event_key:
                # 递归调用业务逻辑
                action_reply = _dispatch_scan_logic(user, event_key)
                if action_reply:
                    reply_content += f"\n\n{action_reply}"
            
            return TextReply(content=reply_content, message=message)

        elif message.event == 'scan':
            user = auth_service.get_or_create_wechat_user(user_openid)[0]
            event_key = _get_event_key(message)
            reply_content = _dispatch_scan_logic(user, event_key)
            if reply_content:
                return TextReply(content=reply_content, message=message)
                
        elif message.event == 'unsubscribe':
            auth_service.unsubscribe_user(user_openid)
            return None

    # 2. 文本消息
    if message.type == "text":
        keyword = (message.content or "").strip()
        reply = REPLY_RULES.get(keyword, DEFAULT_REPLY)
        return TextReply(content=reply, message=message)

    return None

def _dispatch_scan_logic(user, event_key):
    """
    分发扫码逻辑
    param event_key: 例如 'bind_sales_12'
    """
    if not event_key:
        return None
        
    # 分割前缀和ID，例如 bind_sales 和 12
    try:
    # 找到最后一个下划线，分割为 type 和 id
        prefix, object_id_str = event_key.rsplit('_', 1)
        object_id = int(object_id_str)
        
        handler = QR_HANDLERS.get(prefix)
        if handler:
            return handler(user, object_id)
        
    except (ValueError, IndexError):
        logger.warning(f"无法解析二维码参数: {event_key}")
    
    return None
