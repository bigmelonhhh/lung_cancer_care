from __future__ import annotations

from .hrt import HrtCallbackAdapter


_ADAPTERS = {
    "HRT": HrtCallbackAdapter,
}


def get_device_provider_adapter(provider_code: str):
    code = (provider_code or "").strip().upper()
    try:
        return _ADAPTERS[code]()
    except KeyError as exc:
        raise ValueError(f"Unsupported device provider: {provider_code}") from exc
