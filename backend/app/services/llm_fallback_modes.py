from __future__ import annotations

import os
from enum import Enum
from typing import Any


TRUE_VALUES = {"1", "true", "yes", "on"}


class LLMRuntimeMode(str, Enum):
    DISABLED = "disabled"
    FAKE = "fake"
    REPLAY = "replay"
    SHADOW = "shadow"
    LIVE = "live"


def parse_llm_fallback_mode(value: str | None) -> tuple[LLMRuntimeMode, str | None]:
    raw = (value or LLMRuntimeMode.DISABLED.value).strip().lower()
    try:
        return LLMRuntimeMode(raw), None
    except ValueError:
        return LLMRuntimeMode.DISABLED, f"unknown_llm_fallback_mode:{raw}"


def get_llm_fallback_mode(value: str | None = None) -> LLMRuntimeMode:
    configured = os.getenv("LLM_FALLBACK_MODE") if value is None else value
    return parse_llm_fallback_mode(configured)[0]


def is_live_llm_allowed(
    *,
    mode: LLMRuntimeMode | None = None,
    enabled: bool | None = None,
    allow_live: bool | None = None,
) -> bool:
    selected = mode or get_llm_fallback_mode()
    enabled_value = _env_bool("LLM_FALLBACK_ENABLED") if enabled is None else enabled
    allow_value = _env_bool("ALLOW_LIVE_LLM") if allow_live is None else allow_live
    return selected is LLMRuntimeMode.LIVE and enabled_value and allow_value


def describe_llm_runtime_safety(
    *,
    mode: LLMRuntimeMode,
    enabled: bool,
    allow_live: bool,
    config_error: str | None = None,
    sandbox_source: str | None = None,
) -> dict[str, Any]:
    """Return credential-free runtime facts suitable for logs and health output."""
    return {
        "mode": mode.value,
        "enabled": enabled,
        "allowLive": allow_live,
        "networkAllowed": is_live_llm_allowed(mode=mode, enabled=enabled, allow_live=allow_live),
        "shadow": mode is LLMRuntimeMode.SHADOW,
        "sandboxSource": sandbox_source,
        "configError": config_error,
    }


def _env_bool(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in TRUE_VALUES
