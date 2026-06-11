from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from dotenv import dotenv_values


TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off", ""}

VALID_TTS_STYLES = {"friendly", "calm", "clear", "professional", "cute", "fast", "elder_friendly"}
VALID_TTS_PROVIDERS = {"auto", "pyttsx3"}

STYLE_PRESETS: dict[str, dict[str, Any]] = {
    "friendly":       {"rate": 190, "volume": 1.0, "pitch": 1.05},
    "calm":           {"rate": 170, "volume": 1.0, "pitch": 0.98},
    "clear":          {"rate": 180, "volume": 1.0, "pitch": 1.0},
    "professional":   {"rate": 185, "volume": 1.0, "pitch": 1.0},
    "cute":           {"rate": 195, "volume": 1.0, "pitch": 1.08},
    "fast":           {"rate": 215, "volume": 1.0, "pitch": 1.0},
    "elder_friendly": {"rate": 155, "volume": 1.0, "pitch": 1.0},
}


def parse_bool(value: str | None) -> bool:
    if value is None:
        return False
    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    return False


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve_env_file() -> tuple[Path, bool, list[str]]:
    hints: list[str] = []
    configured = os.getenv("BACKEND_ENV_FILE")
    if configured:
        path = Path(configured)
        if not path.is_absolute():
            path = Path.cwd() / path
        path = path.resolve()
        exists = path.exists()
        if not exists:
            hints.append(f"BACKEND_ENV_FILE points to a missing file: {path}")
        return path, exists, hints

    path = (_backend_root() / ".env").resolve()
    exists = path.exists()
    if not exists:
        hints.append(f"No backend .env file found at {path}")
    return path, exists, hints


@dataclass
class VoiceConfig:
    voice_enabled: bool = False
    asr_engine: str = "vosk"
    vosk_model_path: str = "./models/asr/vosk-cn"
    asr_sample_rate: int = 16000
    asr_language: str = "zh-cn"
    asr_final_silence_ms: int = 800
    asr_max_utterance_ms: int = 12000
    tts_enabled: bool = True
    tts_engine: str = "pyttsx3"
    tts_rate: int = 180
    tts_volume: float = 1.0
    tts_voice_name: str = ""
    tts_playback_target: str = "server"
    tts_engine_recreate_per_task: bool = True
    voice_debug: bool = False
    tts_style: str = "friendly"
    tts_pitch: float = 1.05
    tts_lang: str = "zh-CN"
    tts_provider: str = "auto"
    piper_bin: str = ""
    piper_model_path: str = ""
    piper_config_path: str = ""
    whisper_cpp_bin: str = ""
    whisper_model_path: str = ""
    env_file_path: str = ""
    env_file_exists: bool = False
    config_hints: list[str] = field(default_factory=list)
    _explicit_vars: set[str] = field(default_factory=set)

    @classmethod
    def from_env(cls) -> "VoiceConfig":
        return get_voice_settings()


def _clamp_rate(value: int) -> int:
    return max(80, min(260, value))


def _clamp_volume(value: float) -> float:
    return max(0.0, min(1.0, value))


def _clamp_pitch(value: float) -> float:
    return max(0.5, min(2.0, value))


def _safe_float(value: str, default: float) -> float:
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _safe_int(value: str, default: int) -> int:
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def resolve_effective_tts_params(config: VoiceConfig) -> dict[str, Any]:
    """Resolve effective TTS parameters from config with correct priority.

    Priority (highest first):
    1. VOICE_TTS_RATE/VOLUME/VOICE explicitly set
    2. TTS_RATE/VOLUME/VOICE_NAME explicitly set (compat override of preset)
    3. Style preset
    4. Hardcoded fallback
    """
    hints: list[str] = []
    legacy_used = False

    style = config.tts_style
    if style not in VALID_TTS_STYLES:
        hints.append(f"Unknown VOICE_TTS_STYLE '{style}', falling back to 'friendly'")
        style = "friendly"
    preset = STYLE_PRESETS.get(style, STYLE_PRESETS["friendly"])

    requested_provider = config.tts_provider
    resolved_provider = _resolve_provider(requested_provider, config.tts_engine, hints)

    resolved_voice, voice_fallback_reason = _resolve_voice(config, hints)

    rate = _resolve_rate(config, preset, hints)
    volume = _resolve_volume(config, preset, hints)
    configured_pitch = _resolve_pitch(config, preset, hints)

    if _old_tts_vars_explicit(config):
        legacy_used = True

    return {
        "enabled": config.tts_enabled,
        "requestedProvider": requested_provider,
        "resolvedProvider": resolved_provider,
        "providerFallbackReason": "unsupported_provider_requested" if resolved_provider != requested_provider and requested_provider not in VALID_TTS_PROVIDERS else None,
        "style": style,
        "configuredVoice": config.tts_voice_name,
        "resolvedVoice": resolved_voice,
        "resolvedVoiceAvailable": resolved_voice is not None,
        "resolvedVoiceUnavailableReason": None if resolved_voice is not None else "status_endpoint_is_read_only",
        "voiceFallbackReason": voice_fallback_reason,
        "rate": _clamp_rate(rate),
        "volume": _clamp_volume(volume),
        "configuredPitch": _clamp_pitch(configured_pitch),
        "appliedPitch": None,
        "lang": config.tts_lang,
        "legacyConfigUsed": legacy_used,
        "providerCapabilities": {
            "voice": True,
            "rate": True,
            "volume": True,
            "pitch": False,
        },
        "unsupportedParams": ["pitch"],
        "effectiveConfig": {
            "style": style,
            "rate": _clamp_rate(rate),
            "volume": _clamp_volume(volume),
            "configuredPitch": _clamp_pitch(configured_pitch),
            "appliedPitch": None,
            "lang": config.tts_lang,
            "provider": resolved_provider,
        },
        "hints": hints,
    }


def _resolve_provider(requested: str, tts_engine: str, hints: list[str]) -> str:
    if requested in VALID_TTS_PROVIDERS:
        if requested == "auto":
            return tts_engine if tts_engine in ("pyttsx3",) else "pyttsx3"
        return requested
    hints.append(f"Unsupported VOICE_TTS_PROVIDER '{requested}', falling back to 'pyttsx3'")
    return "pyttsx3"


def _resolve_voice(config: VoiceConfig, hints: list[str]) -> tuple[str | None, str | None]:
    if config.tts_voice_name:
        return config.tts_voice_name, None
    return None, None


def _resolve_rate(config: VoiceConfig, preset: dict[str, Any], hints: list[str]) -> int:
    if "VOICE_TTS_RATE" in config._explicit_vars:
        raw = os.getenv("VOICE_TTS_RATE", "")
        if raw:
            return _safe_int(raw, preset["rate"])
    if "TTS_RATE" in config._explicit_vars:
        return config.tts_rate
    return preset["rate"]


def _resolve_volume(config: VoiceConfig, preset: dict[str, Any], hints: list[str]) -> float:
    if "VOICE_TTS_VOLUME" in config._explicit_vars:
        raw = os.getenv("VOICE_TTS_VOLUME", "")
        if raw:
            return _safe_float(raw, preset["volume"])
    if "TTS_VOLUME" in config._explicit_vars:
        return config.tts_volume
    return preset["volume"]


def _resolve_pitch(config: VoiceConfig, preset: dict[str, Any], hints: list[str]) -> float:
    if "VOICE_TTS_PITCH" in config._explicit_vars:
        raw = os.getenv("VOICE_TTS_PITCH", "")
        if raw:
            return _safe_float(raw, preset["pitch"])
    return preset["pitch"]


def _old_tts_vars_explicit(config: VoiceConfig) -> bool:
    old_vars = {"TTS_ENABLED", "TTS_RATE", "TTS_VOLUME", "TTS_VOICE_NAME", "TTS_ENGINE"}
    return bool(config._explicit_vars & old_vars)


@lru_cache(maxsize=1)
def get_voice_settings() -> VoiceConfig:
    env_path, env_exists, hints = _resolve_env_file()
    file_values = dotenv_values(env_path) if env_exists else {}
    explicit_vars: set[str] = set()

    def env(name: str, default: str = "") -> str:
        value = os.getenv(name)
        if value is not None:
            explicit_vars.add(name)
            return value
        file_value = file_values.get(name)
        if file_value is not None and str(file_value) != "":
            explicit_vars.add(name)
            return str(file_value)
        return default

    def int_value(name: str, default: int) -> int:
        try:
            return int(env(name, str(default)))
        except ValueError:
            return default

    def float_value(name: str, default: float) -> float:
        try:
            return float(env(name, str(default)))
        except ValueError:
            return default

    voice_enabled_value = env("VOICE_ENABLED")
    tts_enabled_value = _resolve_tts_enabled(file_values)
    tts_engine_recreate_value = env("TTS_ENGINE_RECREATE_PER_TASK", "true")
    voice_debug_value = env("VOICE_DEBUG", "false")

    if voice_enabled_value not in (None, "") and not _is_bool_literal(voice_enabled_value):
        hints.append("VOICE_ENABLED has an invalid boolean value and was treated as false.")
    if tts_enabled_value not in (None, "") and not _is_bool_literal(tts_enabled_value):
        hints.append("TTS_ENABLED has an invalid boolean value and was treated as false.")
    if tts_engine_recreate_value not in (None, "") and not _is_bool_literal(tts_engine_recreate_value):
        hints.append("TTS_ENGINE_RECREATE_PER_TASK has an invalid boolean value and was treated as false.")
    if voice_debug_value not in (None, "") and not _is_bool_literal(voice_debug_value):
        hints.append("VOICE_DEBUG has an invalid boolean value and was treated as false.")
    raw_vosk_model_path = env("VOSK_MODEL_PATH", "./models/asr/vosk-cn")
    vosk_model_path = _resolve_path_from_env_file(raw_vosk_model_path, env_path)

    tts_style = env("VOICE_TTS_STYLE", "friendly")
    tts_provider = env("VOICE_TTS_PROVIDER", "auto")
    tts_lang = env("VOICE_TTS_LANG", "zh-CN")

    if tts_style not in VALID_TTS_STYLES and tts_style not in ("",):
        hints.append(f"VOICE_TTS_STYLE '{tts_style}' is unknown, will fallback to 'friendly'")
    if tts_provider not in VALID_TTS_PROVIDERS and tts_provider not in ("",):
        hints.append(f"VOICE_TTS_PROVIDER '{tts_provider}' is unsupported, will fallback to 'pyttsx3'")

    return VoiceConfig(
        voice_enabled=parse_bool(voice_enabled_value),
        asr_engine=env("ASR_ENGINE", "vosk"),
        vosk_model_path=vosk_model_path,
        asr_sample_rate=int_value("ASR_SAMPLE_RATE", 16000),
        asr_language=env("ASR_LANGUAGE", "zh-cn"),
        asr_final_silence_ms=int_value("ASR_FINAL_SILENCE_MS", 800),
        asr_max_utterance_ms=int_value("ASR_MAX_UTTERANCE_MS", 12000),
        tts_enabled=parse_bool(tts_enabled_value),
        tts_engine=env("TTS_ENGINE", "pyttsx3"),
        tts_rate=int_value("TTS_RATE", 180),
        tts_volume=float_value("TTS_VOLUME", 1.0),
        tts_voice_name=env("TTS_VOICE_NAME", ""),
        tts_playback_target=env("TTS_PLAYBACK_TARGET", "server"),
        tts_engine_recreate_per_task=parse_bool(tts_engine_recreate_value),
        voice_debug=parse_bool(voice_debug_value),
        tts_style=tts_style if tts_style in VALID_TTS_STYLES else "friendly",
        tts_pitch=float_value("VOICE_TTS_PITCH", 1.05),
        tts_lang=tts_lang,
        tts_provider=tts_provider if tts_provider in VALID_TTS_PROVIDERS else "auto",
        piper_bin=env("PIPER_BIN", ""),
        piper_model_path=env("PIPER_MODEL_PATH", ""),
        piper_config_path=env("PIPER_CONFIG_PATH", ""),
        whisper_cpp_bin=env("WHISPER_CPP_BIN", ""),
        whisper_model_path=env("WHISPER_MODEL_PATH", ""),
        env_file_path=str(env_path),
        env_file_exists=env_exists,
        config_hints=hints,
        _explicit_vars=explicit_vars,
    )


def _is_explicit_in_source(name: str, file_values: dict[str, str | None]) -> bool:
    if name in os.environ:
        return True
    if name in file_values and file_values[name] not in (None, ""):
        return True
    return False


def _explicit_value_from_source(name: str, file_values: dict[str, str | None], default: str = "") -> str:
    if name in os.environ:
        return os.environ[name]
    val = file_values.get(name)
    if val is not None and val != "":
        return str(val)
    return default


def _resolve_tts_enabled(file_values: dict[str, str | None]) -> str:
    if _is_explicit_in_source("VOICE_TTS_ENABLED", file_values):
        return _explicit_value_from_source("VOICE_TTS_ENABLED", file_values, "true")
    if _is_explicit_in_source("TTS_ENABLED", file_values):
        return _explicit_value_from_source("TTS_ENABLED", file_values, "true")
    return "true"


def clear_settings_cache() -> None:
    get_voice_settings.cache_clear()


def _is_bool_literal(value: str | None) -> bool:
    if value is None:
        return True
    return value.strip().lower() in TRUE_VALUES | FALSE_VALUES


def _resolve_path_from_env_file(raw_path: str, env_path: Path) -> str:
    path = Path(raw_path)
    if path.is_absolute():
        return str(path)
    return str((env_path.parent / path).resolve())
