from __future__ import annotations

import base64
import json
import mimetypes
from typing import Any
from urllib.parse import unquote, urlparse

import requests
from django.conf import settings
from django.core.files.storage import default_storage

from ai_vision.exceptions import AiVisionConfigurationError, AiVisionResponseError


DEFAULT_TIMEOUT = 120.0
IMAGE_FETCH_TIMEOUT = 30.0


def _resolve_required_setting(name: str) -> str:
    value = str(getattr(settings, name, "") or "").strip()
    if not value:
        raise AiVisionConfigurationError(f"未配置 {name}，无法调用豆包视觉模型。")
    return value


def _iter_local_image_base_urls() -> list[str]:
    return [
        str(value).rstrip("/")
        for value in (
            getattr(settings, "AI_VISION_IMAGE_BASE_URL", "") or "",
            getattr(settings, "WEB_BASE_URL", "") or "",
        )
        if str(value).strip()
    ]


def _normalize_media_url() -> str:
    media_url = str(getattr(settings, "MEDIA_URL", "/media/") or "/media/").strip()
    if not media_url.startswith("/"):
        media_url = f"/{media_url}"
    if not media_url.endswith("/"):
        media_url = f"{media_url}/"
    return media_url


def _build_public_image_fetch_url(image_url: str) -> str | None:
    text = str(image_url or "").strip()
    if not text:
        raise AiVisionResponseError("ReportImage.image_url 为空，无法发起 AI 解析。")

    if text.startswith(("http://", "https://")):
        return text

    if text.startswith("/"):
        base_url = next(iter(_iter_local_image_base_urls()), "")
        if base_url:
            return f"{base_url}{text}"
        return None

    return None


def _resolve_storage_path(image_url: str) -> str | None:
    text = str(image_url or "").strip()
    if not text:
        raise AiVisionResponseError("ReportImage.image_url 为空，无法发起 AI 解析。")

    media_url = _normalize_media_url()
    parsed = urlparse(text)

    if parsed.scheme:
        parsed_path = parsed.path or ""
        parsed_origin = f"{parsed.scheme}://{parsed.netloc}"
        if parsed_origin not in _iter_local_image_base_urls():
            return None
        if not parsed_path.startswith(media_url):
            return None
        return unquote(parsed_path[len(media_url):].lstrip("/"))

    if text.startswith("/"):
        if not text.startswith(media_url):
            return None
        return unquote(text[len(media_url):].lstrip("/"))

    return unquote(text.lstrip("/"))


def _detect_image_media_type(path_hint: str, data: bytes, header_value: str = "") -> str:
    content_type = str(header_value or "").split(";", 1)[0].strip().lower()
    if content_type.startswith("image/"):
        return content_type

    guessed_type, _ = mimetypes.guess_type(path_hint)
    if guessed_type and guessed_type.startswith("image/"):
        return guessed_type

    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:6] in {b"GIF87a", b"GIF89a"}:
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"BM"):
        return "image/bmp"
    if data.startswith((b"II*\x00", b"MM\x00*")):
        return "image/tiff"

    raise AiVisionResponseError(f"无法识别图片格式: {path_hint or 'unknown'}")


def _read_image_bytes_from_storage(storage_path: str) -> tuple[bytes, str]:
    try:
        with default_storage.open(storage_path, "rb") as image_file:
            data = image_file.read()
    except OSError as exc:
        raise AiVisionResponseError(f"读取本地图片失败: {storage_path}") from exc

    if not data:
        raise AiVisionResponseError(f"本地图片内容为空: {storage_path}")

    return data, _detect_image_media_type(storage_path, data)


def _download_image_bytes(url: str, *, timeout: float = IMAGE_FETCH_TIMEOUT) -> tuple[bytes, str]:
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise AiVisionResponseError(f"服务端下载图片失败: {url}") from exc

    data = response.content
    if not data:
        raise AiVisionResponseError(f"服务端下载到空图片内容: {url}")

    media_type = _detect_image_media_type(
        urlparse(url).path,
        data,
        header_value=response.headers.get("Content-Type", ""),
    )
    return data, media_type


def build_doubao_image_data_url(image_url: str) -> str:
    text = str(image_url or "").strip()
    if not text:
        raise AiVisionResponseError("ReportImage.image_url 为空，无法发起 AI 解析。")

    storage_path = _resolve_storage_path(text)
    if storage_path:
        try:
            data, media_type = _read_image_bytes_from_storage(storage_path)
        except AiVisionResponseError:
            public_url = _build_public_image_fetch_url(text)
            if not public_url:
                raise
            data, media_type = _download_image_bytes(public_url)
    else:
        public_url = _build_public_image_fetch_url(text)
        if not public_url:
            raise AiVisionResponseError(f"无法解析图片地址: {text}")
        data, media_type = _download_image_bytes(public_url)

    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


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
                            "url": build_doubao_image_data_url(image_url),
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
