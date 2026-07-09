import logging

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from business_support.services.device_integrations.base import DeviceCallbackParseError
from business_support.services.device_integrations.registry import get_device_provider_adapter
from health_data.services.device_metric_ingestion import DeviceMetricIngestionService

logger = logging.getLogger(__name__)


@csrf_exempt  # 必须免除 CSRF，因为是外部服务器调用
def smartwatch_data_callback(request, provider="HRT"):
    if request.method != "POST":
        return JsonResponse({"errorCode": 1, "msg": "Method not allowed"})

    try:
        adapter = get_device_provider_adapter(provider)
    except ValueError:
        logger.warning("未知设备厂商回调 provider=%s", provider)
        return JsonResponse({"errorCode": 1, "msg": "Unsupported device provider"})

    if not adapter.verify_signature(request):
        return adapter.error_response("Signature verification failed")

    try:
        payload = adapter.parse_body(request.body)
        logger.info(
            "收到设备数据回调: Provider=%s, Type=%s, Readings=%s",
            payload.provider_code,
            payload.raw_event_type,
            len(payload.readings),
        )
        DeviceMetricIngestionService.ingest_readings(payload.readings)
        return adapter.success_response()

    except DeviceCallbackParseError as exc:
        return adapter.error_response(str(exc) or "Invalid JSON")
    except Exception as exc:  # noqa: BLE001
        logger.error("处理回调异常: %s", exc)
        return adapter.error_response("Internal Error")
