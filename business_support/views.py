import json
import logging

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from business_support.service.device import SmartWatchService
from health_data.services.health_metric import HealthMetricService

logger = logging.getLogger(__name__)


@csrf_exempt  # 必须免除 CSRF，因为是外部服务器调用
def smartwatch_data_callback(request):
    if request.method != "POST":
        return JsonResponse({"errorCode": 1, "msg": "Method not allowed"})

    # 1. 安全验证 (签名校验)
    if not SmartWatchService.verify_callback_signature(request):
        return JsonResponse({"errorCode": 1, "msg": "Signature verification failed"})

    try:
        # 2. 解析数据
        data = json.loads(request.body)
        event_type = data.get("eventType")
        payload = data.get("data", {})

        logger.info("收到手表数据回调: Type=%s, Data=%s", event_type, payload)

        # 3. 业务处理
        # eventType: 1 代表手表数据
        if event_type == 1 and isinstance(payload, dict):
            HealthMetricService.handle_payload(payload)

        # 4. 返回成功响应
        return JsonResponse({"errorCode": 0, "msg": "success"})

    except json.JSONDecodeError:
        return JsonResponse({"errorCode": 1, "msg": "Invalid JSON"})
    except Exception as exc:  # noqa: BLE001
        logger.error("处理回调异常: %s", exc)
        return JsonResponse({"errorCode": 1, "msg": "Internal Error"})
