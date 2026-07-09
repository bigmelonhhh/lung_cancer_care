from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import requests
from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone

from health_data.models import MetricType

from .base import DeviceCallbackParseError, DeviceCallbackPayload, DeviceMetricReading


logger = logging.getLogger(__name__)


class HrtWatchService:
    """HRT smartwatch API helper for signature verification and outbound messages."""

    @staticmethod
    def _get_sha1(text):
        return hashlib.sha1(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _get_md5(text_or_bytes):
        if isinstance(text_or_bytes, str):
            text_or_bytes = text_or_bytes.encode("utf-8")
        return hashlib.md5(text_or_bytes).hexdigest()

    @staticmethod
    def _truncate_by_bytes(text: str, max_bytes: int) -> str:
        if not text or max_bytes <= 0:
            return ""
        encoded = text.encode("utf-8")
        if len(encoded) <= max_bytes:
            return text
        out = ""
        for ch in text:
            candidate = (out + ch).encode("utf-8")
            if len(candidate) > max_bytes:
                break
            out += ch
        return out

    @classmethod
    def send_message(cls, device_no, title, content):
        """
        Send a message to an HRT watch.
        """
        config = settings.SMARTWATCH_CONFIG
        app_key = config["APP_KEY"]
        app_secret = config["APP_SECRET"]

        title = cls._truncate_by_bytes(str(title or "").strip(), 8)
        content = cls._truncate_by_bytes(str(content or "").strip(), 80)
        if not title:
            return False, "标题不能为空"
        if not content:
            return False, "内容不能为空"

        def _send_request(cur_time_value: str):
            nonce = str(uuid.uuid4()).replace("-", "")
            raw_str = app_secret + nonce + cur_time_value
            check_sum = cls._get_sha1(raw_str)
            headers = {
                "AppKey": app_key,
                "Nonce": nonce,
                "CurTime": cur_time_value,
                "CheckSum": check_sum,
                "Content-Type": "application/json; charset=utf-8",
            }
            payload = {
                "appKey": app_key,
                "deviceNo": device_no,
                "messageTitle": title,
                "messageContent": content,
                "messageCont": content,
            }
            url = f"{config['API_BASE_URL']}/api/hrt/app/device/watch/message"
            response = requests.post(url, headers=headers, json=payload, timeout=5)
            return response.json()

        def _curtime_candidates() -> list[str]:
            try:
                now = timezone.localtime()
                base = now.timestamp()
            except Exception:
                base = time.time()
            return [str(int(base)), str(int(base * 1000))]

        try:
            res_json = None
            for cur_time_value in _curtime_candidates():
                res_json = _send_request(cur_time_value)
                if res_json.get("code") not in ("E020204", "E020206"):
                    break

            if res_json.get("code") == "E000000":
                return True, res_json.get("data", {}).get("msgId")
            logger.error("HRT 手表消息发送失败: %s", res_json)
            return False, res_json.get("message")
        except Exception as exc:  # noqa: BLE001
            logger.error("HRT 手表接口网络异常: %s", exc)
            return False, str(exc)

    @classmethod
    def verify_callback_signature(cls, request):
        """Verify HRT callback headers against the raw request body."""
        config = settings.SMARTWATCH_CONFIG
        app_secret = config["APP_SECRET"]

        req_md5 = request.META.get("HTTP_MD5")
        req_checksum = request.META.get("HTTP_CHECKSUM")
        req_curtime = request.META.get("HTTP_CURTIME")

        if not (req_md5 and req_checksum and req_curtime):
            logger.warning("HRT 回调请求缺少必要 Header")
            return False

        body_bytes = request.body
        my_md5 = cls._get_md5(body_bytes)
        if my_md5.lower() != req_md5.lower():
            logger.warning("HRT Body MD5 不匹配: 接收=%s, 计算=%s", req_md5, my_md5)
            return False

        raw_str = app_secret + req_md5 + req_curtime
        my_checksum = cls._get_sha1(raw_str)
        if my_checksum.lower() == req_checksum.lower():
            return True

        logger.warning("HRT CheckSum 不匹配: 接收=%s, 计算=%s", req_checksum, my_checksum)
        return False


class HrtCallbackAdapter:
    provider_code = "HRT"

    def verify_signature(self, request) -> bool:
        return HrtWatchService.verify_callback_signature(request)

    def success_response(self) -> JsonResponse:
        return JsonResponse({"errorCode": 0, "msg": "success"})

    def error_response(self, message: str, *, status: int = 200) -> JsonResponse:
        return JsonResponse({"errorCode": 1, "msg": message}, status=status)

    def parse_body(self, body: bytes | str) -> DeviceCallbackPayload:
        try:
            if isinstance(body, bytes):
                data = json.loads(body.decode("utf-8"))
            else:
                data = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise DeviceCallbackParseError("Invalid JSON") from exc

        if not isinstance(data, dict):
            raise DeviceCallbackParseError("Invalid JSON")

        event_type = data.get("eventType")
        payload = data.get("data", {})
        if event_type != 1 or not isinstance(payload, dict):
            return DeviceCallbackPayload(
                provider_code=self.provider_code,
                raw_event_type=event_type,
                readings=[],
                raw_payload=data,
            )

        readings = self.parse_metric_payload(payload)
        return DeviceCallbackPayload(
            provider_code=self.provider_code,
            raw_event_type=event_type,
            readings=readings,
            raw_payload=data,
        )

    def parse_metric_payload(self, payload: dict[str, Any]) -> list[DeviceMetricReading]:
        metric_type = (payload.get("type") or "").upper()
        if not metric_type:
            logger.warning("HRT 回调数据缺少 type 字段: %s", payload)
            return []

        if metric_type == "BPG":
            return self._parse_bpg(payload)
        if metric_type == "WATCH":
            return self._parse_watch(payload)
        if metric_type == "WS":
            reading = self._parse_weight(payload)
            return [reading] if reading else []

        logger.info("收到未知 HRT type=%s 的数据，暂不处理。payload=%s", metric_type, payload)
        return []

    def _parse_bpg(self, payload: dict[str, Any]) -> list[DeviceMetricReading]:
        context = self._build_context(payload)
        if not context:
            return []
        bpg_data = payload.get("bpgData") or {}
        readings: list[DeviceMetricReading] = []

        sbp = bpg_data.get("sbp")
        dbp = bpg_data.get("dbp")
        if sbp is not None and dbp is not None:
            bp_reading = self._build_reading(
                context,
                MetricType.BLOOD_PRESSURE,
                value_main=sbp,
                value_sub=dbp,
                raw_payload=payload,
            )
            if bp_reading:
                readings.append(bp_reading)
        elif sbp is not None or dbp is not None:
            logger.warning("HRT 血压数据不完整，跳过。payload=%s", payload)

        heart_rate = bpg_data.get("hr")
        if heart_rate is not None:
            hr_reading = self._build_reading(
                context,
                MetricType.HEART_RATE,
                value_main=heart_rate,
                raw_payload=payload,
            )
            if hr_reading:
                readings.append(hr_reading)

        return readings

    def _parse_watch(self, payload: dict[str, Any]) -> list[DeviceMetricReading]:
        context = self._build_context(payload)
        if not context:
            return []
        watch_data = payload.get("watchData") or {}
        readings: list[DeviceMetricReading] = []

        spo_data = watch_data.get("spo") or {}
        if "spo" in watch_data:
            avg_oxy = spo_data.get("agvOxy")
            if avg_oxy is None:
                logger.warning("HRT 血氧数据不完整，跳过。payload=%s", payload)
            else:
                spo_reading = self._build_reading(
                    context,
                    MetricType.BLOOD_OXYGEN,
                    value_main=avg_oxy,
                    raw_payload=payload,
                )
                if spo_reading:
                    readings.append(spo_reading)

        pedo_data = watch_data.get("pedo") or {}
        if "pedo" in watch_data:
            steps = pedo_data.get("step")
            if steps is None:
                logger.warning("HRT 步数数据不完整，跳过。payload=%s", payload)
            else:
                step_reading = self._build_reading(
                    context,
                    MetricType.STEPS,
                    value_main=steps,
                    raw_payload=payload,
                )
                if step_reading:
                    readings.append(step_reading)

        heart_rate = watch_data.get("hr")
        if heart_rate is not None:
            hr_reading = self._build_reading(
                context,
                MetricType.HEART_RATE,
                value_main=heart_rate,
                raw_payload=payload,
            )
            if hr_reading:
                readings.append(hr_reading)

        return readings

    def _parse_weight(self, payload: dict[str, Any]) -> DeviceMetricReading | None:
        context = self._build_context(payload)
        if not context:
            return None
        ws_data = payload.get("wsData") or {}
        weight_raw = ws_data.get("weight")
        if weight_raw is None:
            logger.warning("HRT 体重数据不完整，跳过。payload=%s", payload)
            return None
        try:
            weight = Decimal(str(weight_raw)) / Decimal("100")
        except (InvalidOperation, TypeError, ValueError):
            logger.warning("HRT 体重数据格式错误，跳过。payload=%s", payload)
            return None
        return DeviceMetricReading(
            provider_code=self.provider_code,
            device_no=context["device_no"],
            measured_at=context["measured_at"],
            metric_type=MetricType.WEIGHT,
            value_main=weight,
            raw_payload=payload,
        )

    def _build_context(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        device_no = payload.get("deviceNo")
        if not device_no:
            logger.warning("HRT 回调数据缺少 deviceNo，跳过。payload=%s", payload)
            return None
        return {
            "device_no": str(device_no).strip(),
            "measured_at": self._parse_measured_at(payload.get("recordTime")),
        }

    def _build_reading(
        self,
        context: dict[str, Any],
        metric_type: str,
        *,
        value_main,
        value_sub=None,
        raw_payload: dict[str, Any] | None = None,
    ) -> DeviceMetricReading | None:
        try:
            main = Decimal(str(value_main))
            sub = Decimal(str(value_sub)) if value_sub is not None else None
        except (InvalidOperation, TypeError, ValueError):
            logger.warning("HRT 指标数值格式错误，跳过。payload=%s", raw_payload)
            return None
        return DeviceMetricReading(
            provider_code=self.provider_code,
            device_no=context["device_no"],
            measured_at=context["measured_at"],
            metric_type=metric_type,
            value_main=main,
            value_sub=sub,
            raw_payload=raw_payload,
        )

    @staticmethod
    def _parse_measured_at(record_time) -> datetime:
        if record_time is None:
            return timezone.now()
        try:
            timestamp = int(record_time) / 1000.0
            tz = timezone.get_current_timezone()
            return datetime.fromtimestamp(timestamp, tz=tz)
        except Exception:  # noqa: BLE001
            return timezone.now()
