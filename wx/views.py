"""微信公众平台回调入口。"""

import logging

from django.http import HttpResponse
from django.utils.encoding import smart_str
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from wechatpy import parse_message
from wechatpy.exceptions import InvalidSignatureException
from wechatpy.utils import check_signature

from wx.services import get_crypto, handle_message

logger = logging.getLogger(__name__)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def wechat_main(request):
    """处理微信服务器推送的消息，包含验签与加解密。"""

    signature = request.GET.get("signature")
    timestamp = request.GET.get("timestamp")
    nonce = request.GET.get("nonce")
    echostr = request.GET.get("echostr")

    if request.method == "GET":
        try:
            check_signature(get_crypto().token, signature, timestamp, nonce)
            return HttpResponse(echostr or "")
        except InvalidSignatureException:
            logger.exception("[WX] GET 验签失败 signature=%s", signature)
            return HttpResponse("Invalid signature", status=403)

    msg_signature = request.GET.get("msg_signature")
    try:
        encrypted_xml = request.body
        
        decrypted_xml = get_crypto().decrypt_message(
            encrypted_xml, msg_signature, timestamp, nonce
        )
        
        msg = parse_message(decrypted_xml)
        reply = handle_message(msg)
        if reply:
            reply_xml = reply.render()
            encrypted_reply = get_crypto().encrypt_message(
                reply_xml, nonce, timestamp
            )
            return HttpResponse(encrypted_reply, content_type="application/xml")
        return HttpResponse("success")
    except InvalidSignatureException:
        logger.exception("[WX] POST 验签失败 signature=%s", msg_signature)
        return HttpResponse("Invalid signature", status=403)
    except Exception as exc:  # pragma: no cover - unexpected errors
        logger.exception("[WX] 处理消息异常: %s", exc)
        return HttpResponse("error", status=500)
