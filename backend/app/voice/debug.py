from __future__ import annotations

import logging
from typing import Any


AUTO_TTS_LOG_PREFIX = "[voice-auto-tts]"
PREVIEW_LIMIT = 30


def preview_text(text: str | None, limit: int = PREVIEW_LIMIT) -> str:
    return (text or "")[:limit]


def auto_tts_debug_enabled(config: Any, logger: logging.Logger) -> bool:
    return bool(getattr(config, "voice_debug", False)) or logger.isEnabledFor(logging.DEBUG)


def log_auto_tts_debug(logger: logging.Logger, config: Any, event: str, **fields: Any) -> None:
    if not auto_tts_debug_enabled(config, logger):
        return
    payload = {"event": event, **fields}
    level = logging.INFO if getattr(config, "voice_debug", False) else logging.DEBUG
    logger.log(level, "%s %s %s", AUTO_TTS_LOG_PREFIX, event, payload)


def log_tts_config_debug(logger: logging.Logger, config: Any) -> None:
    if not auto_tts_debug_enabled(config, logger):
        return
    from app.voice.config import resolve_effective_tts_params

    effective = resolve_effective_tts_params(config)
    payload = {
        "event": "tts_config_loaded",
        "provider": effective["resolvedProvider"],
        "style": effective["style"],
        "rate": effective["rate"],
        "volume": effective["volume"],
        "configuredPitch": effective["configuredPitch"],
        "appliedPitch": effective["appliedPitch"],
        "lang": effective["lang"],
        "configuredVoice": effective["configuredVoice"] or "(auto-detect)",
        "legacyConfigUsed": effective["legacyConfigUsed"],
    }
    level = logging.INFO if getattr(config, "voice_debug", False) else logging.DEBUG
    logger.log(level, "%s %s %s", AUTO_TTS_LOG_PREFIX, "tts_config_loaded", payload)
