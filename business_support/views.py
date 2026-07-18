import logging

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from business_support.services.device_integrations.base import DeviceCallbackParseError
from business_support.services.device_integrations.iwown import (
    IwownDeviceInfoAdapter,
    IwownHealthDataAdapter,
    IwownPacketHeaderError,
    build_iwown_device_log_fields,
)
from business_support.services.device_integrations.registry import get_device_provider_adapter
from health_data.services.device_metric_ingestion import DeviceMetricIngestionService

logger = logging.getLogger(__name__)


@csrf_exempt
def iwown_device_info_callback(request):
    """Receive and log IWOWN device-information uploads."""
    adapter = IwownDeviceInfoAdapter()
    if request.method != "POST":
        return adapter.invalid_response(status=405)
    body = request.body
    try:
        payload = adapter.parse_body(body)
    except DeviceCallbackParseError as exc:
        adapter.log_invalid(
            body,
            content_type=request.content_type or "",
            error=exc,
        )
        return adapter.invalid_response()
    adapter.log_received(
        payload,
        body_bytes=len(body),
        content_type=request.content_type or "",
    )
    return adapter.success_response()


@csrf_exempt
def iwown_health_data_callback(request):
    """Receive IWOWN binary health packets and ingest supported metrics."""
    adapter = IwownHealthDataAdapter()
    if request.method != "POST":
        return adapter.invalid_data_response(status=405)

    body = request.body
    content_type = request.content_type or ""
    try:
        payload = adapter.parse_body(body)
    except IwownPacketHeaderError as exc:
        adapter.log_invalid(
            body_bytes=len(body),
            content_type=content_type,
            error=exc,
        )
        return adapter.invalid_header_response()
    except DeviceCallbackParseError as exc:
        adapter.log_invalid(
            body_bytes=len(body),
            content_type=content_type,
            error=exc,
        )
        return adapter.invalid_data_response()

    try:
        result = DeviceMetricIngestionService.ingest_readings(payload.readings)
    except Exception:  # noqa: BLE001
        logger.exception(
            {
                "event": "iwown_health_data_ingestion_failed",
                "provider": "IWOWN",
                **build_iwown_device_log_fields(
                    payload.raw_payload.get("device_no")
                ),
            }
        )
        return adapter.invalid_data_response()

    adapter.log_received(
        payload,
        body_bytes=len(body),
        content_type=content_type,
        created_count=result.created_count,
        skipped_count=result.skipped_count,
    )
    return adapter.success_response()


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
