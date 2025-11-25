"""微信公众平台回调入口。"""

import logging

from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from wechatpy import parse_message
from wechatpy.exceptions import InvalidSignatureException
from wechatpy.utils import check_signature

from wx.services import get_crypto, handle_message

logger = logging.getLogger("lung_cancer_care.wx")


@csrf_exempt
@require_http_methods(["GET", "POST"])
def wechat_main(request):
    """处理微信服务器推送的消息，包含验签与加解密。"""

    signature = request.GET.get("signature")
    timestamp = request.GET.get("timestamp")
    nonce = request.GET.get("nonce")
    echostr = request.GET.get("echostr")
    logger.info(
        {
            "event": "wechat_entry",
            "method": request.method,
            "signature": signature,
            "timestamp": timestamp,
            "nonce": nonce,
        }
    )

    if request.method == "GET":
        try:
            check_signature(get_crypto().token, signature, timestamp, nonce)
            return HttpResponse(echostr or "")
        except InvalidSignatureException:
            logger.exception({"event": "wechat_signature_error", "phase": "GET", "signature": signature})
            return HttpResponse("Invalid signature", status=403)

    msg_signature = request.GET.get("msg_signature")
    try:
        encrypted_xml = request.body
        logger.info(
            {
                "event": "wechat_encrypted_request",
                "payload": encrypted_xml.decode("utf-8", errors="ignore") if encrypted_xml else "",
            }
        )
        decrypted_xml = get_crypto().decrypt_message(
            encrypted_xml, msg_signature, timestamp, nonce
        )
        logger.info({"event": "wechat_decrypted_xml", "xml": decrypted_xml})
        msg = parse_message(decrypted_xml)
        reply = handle_message(msg)
        if reply:
            reply_xml = reply.render()
            logger.info(
                {
                    "event": "wechat_reply",
                    "reply_type": reply.type,
                    "reply_content": getattr(reply, "content", ""),
                }
            )
            encrypted_reply = get_crypto().encrypt_message(
                reply_xml, nonce, timestamp
            )
            return HttpResponse(encrypted_reply, content_type="application/xml")
        return HttpResponse("success")
    except InvalidSignatureException:
        logger.exception({"event": "wechat_signature_error", "phase": "POST", "signature": msg_signature})
        return HttpResponse("Invalid signature", status=403)
    except Exception as exc:  # pragma: no cover - unexpected errors
        logger.exception({"event": "wechat_processing_error", "error": str(exc)})
        return HttpResponse("error", status=500)
