from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from app.voice.config import VoiceConfig, resolve_effective_tts_params
from app.voice.tts.base import TTSProvider


logger = logging.getLogger(__name__)

_CHINESE_VOICE_MARKERS_NAME = [
    "chinese", "mandarin", "simplified", "中文", "普通话", "china",
]
_CHINESE_VOICE_MARKERS_ID = [
    "zh", "chs", "chinese", "mandarin",
]
_CHINESE_VOICE_MARKERS_LANG = [
    "zh", "zh-cn", "chinese",
]


class Pyttsx3TTSProvider(TTSProvider):
    def __init__(self, config: VoiceConfig) -> None:
        self.config = config
        self._engine: Any = None
        self._speaking = False
        self._current_voice: dict[str, Any] = {"id": None, "name": "default", "languages": []}
        self._com_warning_logged = False
        self._event_callback: Callable[[dict[str, Any]], None] | None = None
        self._resolved_params: dict[str, Any] | None = None
        self._voice_fallback_reason: str | None = None

    def set_event_callback(self, callback: Callable[[dict[str, Any]], None] | None) -> None:
        self._event_callback = callback

    def speak(self, text: str) -> None:
        if not text:
            return
        if self._resolved_params is None:
            self._resolved_params = resolve_effective_tts_params(self.config)
        if self.config.tts_engine_recreate_per_task:
            self._speak_with_new_engine(text)
        else:
            self._speak_with_reused_engine(text)

    def stop(self) -> None:
        if self._engine is not None:
            try:
                self._engine.stop()
            except Exception as exc:
                logger.warning("voice tts engine stop warning: %s: %s", type(exc).__name__, exc)
        self._speaking = False

    def is_speaking(self) -> bool:
        return self._speaking

    def current_voice(self) -> dict[str, Any]:
        return self._current_voice

    def _get_params(self) -> dict[str, Any]:
        if self._resolved_params is None:
            self._resolved_params = resolve_effective_tts_params(self.config)
        return self._resolved_params

    def _speak_with_new_engine(self, text: str) -> None:
        pythoncom = None
        com_initialized = False
        engine: Any = None
        try:
            pythoncom, com_initialized = self._co_initialize()
            self._emit({"type": "init_started"})
            logger.debug("voice tts pyttsx3 init started")
            engine = self._create_engine()
            self._emit({"type": "init_finished"})
            logger.debug("voice tts pyttsx3 init finished")
            self._configure_engine(engine)
            self._speaking = True
            engine.say(text)
            self._emit({"type": "run_and_wait_started"})
            logger.debug("voice tts pyttsx3 runAndWait started")
            try:
                engine.runAndWait()
            finally:
                self._emit({"type": "run_and_wait_finished"})
                logger.debug("voice tts pyttsx3 runAndWait finished")
        finally:
            self._speaking = False
            self._stop_engine(engine)
            engine = None
            self._co_uninitialize(pythoncom, com_initialized)

    def _speak_with_reused_engine(self, text: str) -> None:
        pythoncom = None
        com_initialized = False
        try:
            pythoncom, com_initialized = self._co_initialize()
            engine = self._get_reused_engine()
            self._speaking = True
            engine.say(text)
            self._emit({"type": "run_and_wait_started"})
            logger.debug("voice tts pyttsx3 runAndWait started")
            try:
                engine.runAndWait()
            finally:
                self._emit({"type": "run_and_wait_finished"})
                logger.debug("voice tts pyttsx3 runAndWait finished")
        finally:
            self._speaking = False
            self._co_uninitialize(pythoncom, com_initialized)

    def _get_reused_engine(self) -> Any:
        if self._engine is None:
            self._emit({"type": "init_started"})
            logger.debug("voice tts pyttsx3 init started")
            self._engine = self._create_engine()
            self._emit({"type": "init_finished"})
            logger.debug("voice tts pyttsx3 init finished")
            self._configure_engine(self._engine)
        return self._engine

    def _create_engine(self) -> Any:
        try:
            import pyttsx3
        except ImportError as exc:
            raise RuntimeError("pyttsx3 is not installed. Install backend voice dependencies first.") from exc
        return pyttsx3.init()

    def _configure_engine(self, engine: Any) -> None:
        params = self._get_params()
        try:
            engine.setProperty("rate", params["rate"])
            logger.debug("voice tts pyttsx3 rate set: %s", params["rate"])
        except Exception as exc:
            logger.warning("voice tts engine rate warning: %s: %s", type(exc).__name__, exc)
        try:
            engine.setProperty("volume", params["volume"])
            logger.debug("voice tts pyttsx3 volume set: %s", params["volume"])
        except Exception as exc:
            logger.warning("voice tts engine volume warning: %s: %s", type(exc).__name__, exc)
        self._select_voice(engine)

    def _select_voice(self, engine: Any) -> None:
        voices: list[Any] = []
        try:
            voices = list(engine.getProperty("voices") or [])
        except Exception as exc:
            logger.warning("voice tts read voices warning: %s: %s", type(exc).__name__, exc)

        logger.debug("voice tts voice count: %s", len(voices))
        params = self._get_params()
        selected = None
        configured = params.get("configuredVoice", "")
        fallback_reason: str | None = None

        if configured and voices:
            selected = _find_voice(voices, configured)
            if selected is None:
                fallback_reason = "configured_voice_missing"
                logger.warning(
                    "voice tts voice warning: configured voice '%s' not found, falling back to Chinese voice",
                    configured,
                )

        if selected is None and voices:
            selected = _find_chinese_voice(voices)
            if selected is not None:
                if fallback_reason is None and configured:
                    fallback_reason = "configured_voice_missing"
                logger.debug("voice tts selected Chinese voice: %s", getattr(selected, "name", "unknown"))
            else:
                if fallback_reason is None:
                    fallback_reason = "chinese_voice_missing" if configured else "chinese_voice_missing"
                logger.warning("voice tts no Chinese voice found, using system default")

        if selected is None and voices:
            selected = voices[0]
            if fallback_reason is None:
                fallback_reason = "provider_default"
            logger.debug("voice tts using system default voice")

        if selected is not None:
            try:
                engine.setProperty("voice", selected.id)
            except Exception as exc:
                logger.warning("voice tts set voice warning: %s: %s", type(exc).__name__, exc)

        current = selected
        current_id = None
        try:
            current_id = engine.getProperty("voice")
            current = next((voice for voice in voices if getattr(voice, "id", None) == current_id), None) or selected
        except Exception as exc:
            logger.warning("voice tts current voice warning: %s: %s", type(exc).__name__, exc)

        self._current_voice = _voice_info(current, fallback_id=current_id)
        self._voice_fallback_reason = fallback_reason
        self._emit({
            "type": "voice_selected",
            "voice": self._current_voice,
            "fallbackReason": fallback_reason,
        })
        logger.debug(
            "voice tts selected voice: id=%s, name=%s, languages=%s, fallback_reason=%s",
            self._current_voice.get("id"),
            self._current_voice.get("name"),
            self._current_voice.get("languages"),
            fallback_reason,
        )

    def _stop_engine(self, engine: Any) -> None:
        if engine is None:
            return
        try:
            engine.stop()
        except Exception as exc:
            logger.warning("voice tts engine stop warning: %s: %s", type(exc).__name__, exc)

    def _co_initialize(self) -> tuple[Any, bool]:
        try:
            import pythoncom as imported_pythoncom  # type: ignore[import-not-found]

            imported_pythoncom.CoInitialize()
            return imported_pythoncom, True
        except ImportError:
            if not self._com_warning_logged:
                logger.warning("voice tts pythoncom warning: pythoncom unavailable; continuing without COM initialization")
                self._com_warning_logged = True
            return None, False

    def _co_uninitialize(self, pythoncom: Any, com_initialized: bool) -> None:
        if not com_initialized or pythoncom is None:
            return
        try:
            pythoncom.CoUninitialize()
        except Exception as exc:
            logger.warning("voice tts pythoncom uninitialize warning: %s: %s", type(exc).__name__, exc)

    def _emit(self, event: dict[str, Any]) -> None:
        if self._event_callback is None:
            return
        try:
            self._event_callback(event)
        except Exception as exc:
            logger.warning("voice tts event callback warning: %s: %s", type(exc).__name__, exc)


def _find_voice(voices: list[Any], configured: str) -> Any | None:
    for voice in voices:
        if getattr(voice, "id", None) == configured:
            return voice
    for voice in voices:
        if getattr(voice, "name", None) == configured:
            return voice
    lowered = configured.lower()
    for voice in voices:
        vid = str(getattr(voice, "id", "") or "").lower()
        if lowered in vid:
            return voice
    for voice in voices:
        name = str(getattr(voice, "name", "") or "").lower()
        if lowered in name:
            return voice
    return None


def _find_chinese_voice(voices: list[Any]) -> Any | None:
    for voice in voices:
        name = str(getattr(voice, "name", "") or "").lower()
        for marker in _CHINESE_VOICE_MARKERS_NAME:
            if marker in name:
                return voice
    for voice in voices:
        vid = str(getattr(voice, "id", "") or "").lower()
        for marker in _CHINESE_VOICE_MARKERS_ID:
            if marker in vid:
                return voice
    for voice in voices:
        languages = getattr(voice, "languages", None)
        if languages and isinstance(languages, (list, tuple)):
            for lang in languages:
                lang_str = lang.decode(errors="ignore") if isinstance(lang, bytes) else str(lang)
                lang_lower = lang_str.lower()
                for marker in _CHINESE_VOICE_MARKERS_LANG:
                    if marker in lang_lower:
                        return voice
    return None


def _voice_info(voice: Any, fallback_id: str | None = None) -> dict[str, Any]:
    if voice is None:
        return {"id": fallback_id, "name": "default", "languages": []}
    return {
        "id": getattr(voice, "id", fallback_id),
        "name": getattr(voice, "name", "default") or "default",
        "languages": _normalize_languages(getattr(voice, "languages", []) or []),
    }


def _normalize_languages(languages: Any) -> list[str]:
    normalized: list[str] = []
    for language in languages if isinstance(languages, (list, tuple)) else [languages]:
        if isinstance(language, bytes):
            normalized.append(language.decode(errors="ignore"))
        else:
            normalized.append(str(language))
    return normalized
