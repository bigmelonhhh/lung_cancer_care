from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

import requests
from django.conf import settings

from ai_vision.exceptions import AiVisionConfigurationError, AiVisionResponseError


DEFAULT_TIMEOUT = 120.0


def _resolve_required_setting(name: str) -> str:
    value = str(getattr(settings, name, "") or "").strip()
    if not value:
        raise AiVisionConfigurationError(f"未配置 {name}，无法调用豆包视觉模型。")
    return value


def build_doubao_image_url_value(image_url: str) -> str:
    text = str(image_url or "").strip()
    if not text:
        raise AiVisionResponseError("ReportImage.image_url 为空，无法发起 AI 解析。")

    if text.startswith(("http://", "https://")):
        return text

    if text.startswith("/"):
        base_url = str(getattr(settings, "AI_VISION_IMAGE_BASE_URL", "") or "").rstrip("/")
        if not base_url:
            base_url = str(getattr(settings, "WEB_BASE_URL", "") or "").rstrip("/")
        if base_url:
            return f"{base_url}{text}"
        raise AiVisionConfigurationError(
            "未配置 AI_VISION_IMAGE_BASE_URL 或 WEB_BASE_URL，无法拼接图片访问地址。"
        )

    raise AiVisionResponseError(f"无法解析图片地址: {text}")


def parse_json_text(text: str, *, source: str) -> dict[str, Any]:
    content = text.strip()
    if content.startswith("```"):
        lines = content.splitlines()
        if len(lines) >= 3:
            content = "\n".join(lines[1:-1]).strip()
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise AiVisionResponseError(f"{source} 返回的内容不是合法 JSON。") from exc
    if not isinstance(data, dict):
        raise AiVisionResponseError(f"{source} 返回的 JSON 顶层不是对象。")
    return data


def request_doubao_report_json(
    *,
    image_url: str,
    prompt: str,
    temperature: float = 0,
    max_tokens: int = 4096,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    api_key = _resolve_required_setting("VOLCENGINE_KEY")
    model_id = _resolve_required_setting("VOLCENGINE_VISION_MODEL_ID")
    base_url = str(
        getattr(settings, "VOLCENGINE_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3") or ""
    ).rstrip("/")
    endpoint = f"{base_url}/chat/completions"
    payload = {
        "model": model_id,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": build_doubao_image_url_value(image_url),
                        },
                    },
                ],
            }
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    response = requests.post(endpoint, headers=headers, json=payload, timeout=timeout)
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise AiVisionResponseError(
            f"豆包接口调用失败: HTTP {response.status_code}: {response.text}"
        ) from exc

    try:
        data = response.json()
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise AiVisionResponseError("豆包接口返回结构异常。") from exc

    return parse_json_text(content if isinstance(content, str) else str(content), source="豆包视觉模型")
