"""Shared normalization helpers for structured checkup data."""

from __future__ import annotations

import re
import unicodedata


_NON_WORD_RE = re.compile(r"[^0-9A-Z\u4e00-\u9fff]+")
_BRACKET_SEGMENT_RE = re.compile(r"[\(\[\{（【].*?[\)\]\}）】]")
_CODE_WITH_SUFFIX_BRACKET_RE = re.compile(
    r"^([A-Z0-9+\-]+)[\(\[\{（【]([A-Z0-9]+)[\)\]\}）】]$"
)
_TOKEN_REPLACEMENTS = {
    "%": "PCT",
    "％": "PCT",
    "#": "ABS",
    "＃": "ABS",
}


def normalize_standard_field_name(value: str | None) -> str:
    """
    Normalize field-like text for alias matching.

    Rules:
    - apply NFKC unicode normalization
    - trim leading/trailing whitespace
    - uppercase latin text
    - drop parenthetical annotations like "(WBC)" or "（化学发光法）"
    - keep key semantic suffixes before removing punctuation
    """

    text = unicodedata.normalize("NFKC", str(value or "")).strip().upper()
    code_match = _CODE_WITH_SUFFIX_BRACKET_RE.match(text)
    if code_match:
        text = f"{code_match.group(1)}{code_match.group(2)}"
    else:
        text_without_brackets = _BRACKET_SEGMENT_RE.sub("", text).strip()
        if text_without_brackets:
            text = text_without_brackets
    for source, target in _TOKEN_REPLACEMENTS.items():
        text = text.replace(source, target)
    return _NON_WORD_RE.sub("", text)
