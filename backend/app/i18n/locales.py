from __future__ import annotations

from typing import Final


ZH_CN: Final = "zh-CN"
YUE_HANT_HK: Final = "yue-Hant-HK"
EN_HK: Final = "en-HK"
MIXED: Final = "mixed"

CONCRETE_LOCALES: Final = (ZH_CN, YUE_HANT_HK, EN_HK)
SUPPORTED_LOCALES: Final = (*CONCRETE_LOCALES, MIXED)
DEFAULT_LOCALE: Final = ZH_CN


def validate_requested_locale(value: str | None, *, allow_mixed: bool = False) -> str | None:
    if value is None:
        return None
    allowed = SUPPORTED_LOCALES if allow_mixed else CONCRETE_LOCALES
    if value not in allowed:
        raise ValueError(f"unsupported locale: {value}")
    return value


def concrete_response_locale(value: str | None, fallback: str = DEFAULT_LOCALE) -> str:
    return value if value in CONCRETE_LOCALES else fallback
