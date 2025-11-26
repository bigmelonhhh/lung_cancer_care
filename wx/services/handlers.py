from .reply_rules import REPLY_RULES, DEFAULT_REPLY
from .client import wechat_client
from wechatpy.replies import TextReply
from users.services.auth import AuthService
from users.services.patient import PatientService

auth_service = AuthService()
patient_service = PatientService()

def handle_message(message):
    """
    微信消息入口
    将微信推送的消息转为业务回复。

    作用：统一管理各类事件/消息的响应策略。
    使用场景：wechat_main 解密出 message 后调用，返回 TextReply 或 None。
    """

    user_openid = message.source

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
        if message.key and message.key.startswith('qrscene_bind_patient_'):
            try:
                profile_id = message.key.split('_')[-1]
                patient_service.bind_user_to_profile(user_openid, profile_id)
                reply_content += "\n您已成功绑定患者档案！"
            except Exception as e:
                reply_content += f"\n绑定失败：{str(e)}"

        return TextReply(content=reply_content, message=message)

    # ---------------------------
    # 2. 扫码事件 (SCAN - 已关注用户扫码)
    # ---------------------------
    if message.type == 'event' and message.event == 'scan':
        # 确保用户存在（理论上已关注必定存在，但防万一）
        auth_service.get_or_create_wechat_user(user_openid)
        
        # 格式通常是 bind_patient_123 (没有 qrscene_ 前缀)
        if message.key and message.key.startswith('bind_patient_'):
            try:
                profile_id = message.key.split('_')[-1]
                patient_service.bind_user_to_profile(user_openid, profile_id)
                return TextReply(content="扫码成功，档案绑定完成！", message=message)
            except Exception as e:
                return TextReply(content=f"绑定失败：{str(e)}", message=message)

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