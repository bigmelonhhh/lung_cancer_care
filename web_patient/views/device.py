import hashlib
import json
import logging
import time
from typing import Any, Dict

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils.crypto import get_random_string
from django.views.decorators.http import require_POST

from business_support.models import Device
from business_support.service import (
    DeviceActionStatus,
    DeviceServiceError,
    bind_device,
    unbind_device,
)
from users.decorators import check_patient, require_membership
from wx.services.client import WX_APPID, wechat_client

logger = logging.getLogger(__name__)


@login_required
@check_patient
@require_membership
def device_list(request: HttpRequest) -> HttpResponse:
    patient = request.patient
    if not patient:
        return render(request, "web_patient/device_list.html", {"devices": [], "wx_config": None})

    devices = (
        Device.objects.filter(current_patient=patient, is_active=True)
        .order_by("-bind_at", "-updated_at")
        .all()
    )

    wx_config = None
    try:
        wx_config = _build_wechat_js_config(request)
    except Exception as exc:  # pragma: no cover - network/env failure
        logger.exception("生成微信 JSSDK 签名失败: %s", exc)

    return render(
        request,
        "web_patient/device_list.html",
        {
            "patient": patient,
            "devices": devices,
            "wx_config": wx_config,
        },
    )


@login_required
@check_patient
@require_membership
@require_POST
def api_bind_device(request: HttpRequest) -> JsonResponse:
    patient = request.patient
    payload = _parse_json_body(request)
    if payload is None:
        return JsonResponse({"success": False, "message": "请求体格式错误"}, status=400)

    scan_data = payload.get("scan_data")
    if not scan_data:
        return JsonResponse({"success": False, "message": "缺少扫码数据"}, status=400)

    try:
        imei = _extract_imei(scan_data)
    except ValueError as exc:
        return JsonResponse({"success": False, "message": str(exc) or "无法解析设备信息"}, status=400)

    try:
        result = bind_device(imei, patient.id)
    except DeviceServiceError as exc:
        return JsonResponse({"success": False, "message": str(exc)}, status=400)

    if result.status == DeviceActionStatus.ALREADY_BOUND:
        message = "该设备已绑定，无需重复操作。"
    else:
        message = "绑定成功，设备数据将自动同步。"

    return JsonResponse(
        {
            "success": True,
            "message": message,
            "status": result.status,
        }
    )


@login_required
@check_patient
@require_membership
@require_POST
def api_unbind_device(request: HttpRequest) -> JsonResponse:
    patient = request.patient
    payload = _parse_json_body(request)
    if payload is None:
        return JsonResponse({"success": False, "message": "请求体格式错误"}, status=400)

    imei = (payload.get("imei") or "").strip()
    if not imei:
        return JsonResponse({"success": False, "message": "缺少 IMEI 参数"}, status=400)

    try:
        result = unbind_device(imei, patient.id)
    except DeviceServiceError as exc:
        return JsonResponse({"success": False, "message": str(exc)}, status=400)

    return JsonResponse(
        {
            "success": True,
            "message": "解绑成功，设备已返回库存。",
            "status": result.status,
        }
    )


def _parse_json_body(request: HttpRequest) -> Dict[str, Any] | None:
    try:
        return json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def _extract_imei(raw_data: Any) -> str:
    """
    接受字符串或字典，提取 IMEI。
    """

    if isinstance(raw_data, dict):
        if "imei" in raw_data:
            value = str(raw_data["imei"]).strip()
            if not value:
                raise ValueError("IMEI 不能为空。")
            return value
        if "dev_info" in raw_data and isinstance(raw_data["dev_info"], dict):
            return _extract_imei(raw_data["dev_info"])
        raise ValueError("未在扫码数据中找到 IMEI。")

    if isinstance(raw_data, str):
        text = raw_data.strip()
        if not text:
            raise ValueError("IMEI 不能为空。")
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return text
        return _extract_imei(data)

    raise ValueError("扫码数据格式不支持。")


def _build_wechat_js_config(request: HttpRequest) -> Dict[str, Any]:
    url = request.build_absolute_uri()
    ticket = wechat_client.jsapi.get_jsapi_ticket()
    nonce_str = get_random_string(16)
    timestamp = int(time.time())

    parsed_url = url.split("#")[0]
    raw = f"jsapi_ticket={ticket}&noncestr={nonce_str}&timestamp={timestamp}&url={parsed_url}"
    signature = hashlib.sha1(raw.encode("utf-8")).hexdigest()

    app_id = getattr(settings, "WECHAT_APP_ID", None) or WX_APPID
    if not app_id:
        raise RuntimeError("WECHAT_APP_ID 未配置")

    return {
        "appId": app_id,
        "timestamp": timestamp,
        "nonceStr": nonce_str,
        "signature": signature,
    }
