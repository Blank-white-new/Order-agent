from __future__ import annotations

import importlib.util
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.voice.asr.vosk_asr import VoskModelManager
from app.voice.config import VoiceConfig, get_voice_settings


DependencyProbe = Callable[[str], bool]


def evaluate_voice_status(
    settings: VoiceConfig | None = None,
    dependency_probe: DependencyProbe | None = None,
) -> dict[str, Any]:
    settings = settings or get_voice_settings()
    dependency_probe = dependency_probe or _dependency_available

    asr_engine = settings.asr_engine.lower()
    tts_engine = settings.tts_engine.lower()
    model_path = Path(settings.vosk_model_path)
    model_path_exists = model_path.exists()
    model_looks_valid = _looks_like_vosk_model(model_path)

    asr_dependency_available = _probe_dependency(asr_engine, dependency_probe)
    tts_dependency_available = True if not settings.tts_enabled else _probe_dependency(tts_engine, dependency_probe)
    model_loaded = settings.vosk_model_path in VoskModelManager._models

    asr_disabled_reason = _asr_disabled_reason(
        settings=settings,
        asr_dependency_available=asr_dependency_available,
        model_path_exists=model_path_exists,
        model_looks_valid=model_looks_valid,
    )
    tts_disabled_reason = _tts_disabled_reason(
        settings=settings,
        tts_dependency_available=tts_dependency_available,
    )

    asr_ready = asr_dependency_available and model_path_exists and model_looks_valid
    tts_ready = settings.tts_enabled and tts_dependency_available
    can_record = settings.voice_enabled and asr_ready
    can_speak = settings.voice_enabled and tts_ready

    disabled_reason = None
    if not settings.voice_enabled:
        disabled_reason = "后端语音未开启"
    elif not can_record:
        disabled_reason = asr_disabled_reason
    elif settings.tts_enabled and not can_speak:
        disabled_reason = tts_disabled_reason

    hints = _build_hints(
        settings=settings,
        disabled_reason=disabled_reason,
        asr_disabled_reason=asr_disabled_reason,
        tts_disabled_reason=tts_disabled_reason,
    )

    from app.voice.config import resolve_effective_tts_params

    effective = resolve_effective_tts_params(settings)

    return {
        "voiceEnabled": settings.voice_enabled,
        "asrEngine": settings.asr_engine,
        "ttsEnabled": settings.tts_enabled,
        "ttsEngine": settings.tts_engine,
        "ttsPlaybackTarget": settings.tts_playback_target,
        "ttsEngineRecreatePerTask": settings.tts_engine_recreate_per_task,
        "ttsStyle": effective["style"],
        "ttsProvider": effective["resolvedProvider"],
        "ttsRate": effective["rate"],
        "ttsVolume": effective["volume"],
        "ttsConfiguredPitch": effective["configuredPitch"],
        "ttsAppliedPitch": effective["appliedPitch"],
        "ttsLang": effective["lang"],
        "ttsConfiguredVoice": effective["configuredVoice"],
        "ttsProviderCapabilities": effective["providerCapabilities"],
        "ttsUnsupportedParams": effective["unsupportedParams"],
        "asrReady": asr_ready,
        "ttsReady": tts_ready,
        "asrDependencyAvailable": asr_dependency_available,
        "ttsDependencyAvailable": tts_dependency_available,
        "modelPathExists": model_path_exists,
        "modelLooksValid": model_looks_valid,
        "modelLoaded": model_loaded,
        "canRecord": can_record,
        "canSpeak": can_speak,
        "asrDisabledReason": asr_disabled_reason,
        "ttsDisabledReason": tts_disabled_reason,
        "disabledReason": disabled_reason,
        "hints": hints,
        "envFilePath": settings.env_file_path,
        "envFileExists": settings.env_file_exists,
        "voskModelPath": settings.vosk_model_path,
    }


def _dependency_available(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ValueError, AttributeError):
        return False


def _probe_dependency(engine: str, dependency_probe: DependencyProbe) -> bool:
    if engine == "vosk":
        return dependency_probe("vosk")
    if engine == "pyttsx3":
        return dependency_probe("pyttsx3")
    if engine == "piper":
        return True
    if engine == "whisper_cpp":
        return True
    return False


def _looks_like_vosk_model(model_path: Path) -> bool:
    if not model_path.exists() or not model_path.is_dir():
        return False
    try:
        entries = {child.name.lower() for child in model_path.iterdir()}
    except OSError:
        return False
    if not entries:
        return False

    has_conf = "conf" in entries or any(name.endswith(".conf") for name in entries)
    has_acoustic = "am" in entries or "ivector" in entries or any(name.endswith(".mdl") for name in entries)
    has_graph = "graph" in entries or "rescore" in entries or any(name in {"hclg.fst", "words.txt"} for name in entries)
    return has_conf and has_acoustic and has_graph


def _asr_disabled_reason(
    *,
    settings: VoiceConfig,
    asr_dependency_available: bool,
    model_path_exists: bool,
    model_looks_valid: bool,
) -> str | None:
    if settings.asr_engine.lower() != "vosk":
        return f"ASR 引擎暂未支持: {settings.asr_engine}"
    if not asr_dependency_available:
        return "ASR 依赖缺失: vosk"
    if not model_path_exists:
        return f"ASR 模型路径不存在: {settings.vosk_model_path}"
    if not model_looks_valid:
        return f"ASR 模型目录结构无效: {settings.vosk_model_path}"
    return None


def _tts_disabled_reason(*, settings: VoiceConfig, tts_dependency_available: bool) -> str | None:
    if not settings.tts_enabled:
        return "TTS 未启用"
    if settings.tts_engine.lower() == "pyttsx3" and not tts_dependency_available:
        return "TTS 依赖缺失: pyttsx3"
    if settings.tts_engine.lower() not in {"pyttsx3", "piper"}:
        return f"TTS 引擎暂未支持: {settings.tts_engine}"
    return None


def _build_hints(
    *,
    settings: VoiceConfig,
    disabled_reason: str | None,
    asr_disabled_reason: str | None,
    tts_disabled_reason: str | None,
) -> list[str]:
    hints = list(settings.config_hints)
    hints.append(f"Backend env file checked: {settings.env_file_path}")

    if not settings.voice_enabled:
        hints.extend(
            [
                "请在后端 .env 中设置 VOICE_ENABLED=true。",
                "修改 .env 后需要重启 FastAPI 后端。",
                "不要只修改前端 Vite .env。",
            ]
        )
    if asr_disabled_reason:
        hints.append(asr_disabled_reason)
        if "模型" in asr_disabled_reason:
            hints.append("请确认 VOSK_MODEL_PATH 指向解压后的 Vosk 中文模型目录。")
    if tts_disabled_reason:
        hints.append(tts_disabled_reason)
    if settings.tts_playback_target == "server":
        hints.append("TTS_PLAYBACK_TARGET=server 时，声音从运行 FastAPI 的后端本机播放。")
    if disabled_reason and disabled_reason not in hints:
        hints.append(disabled_reason)
    return hints
