from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.voice.config import clear_settings_cache, get_voice_settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Test local pyttsx3 TTS directly, without FastAPI.")
    parser.add_argument("text", nargs="?", default="这是一条语音播报测试。")
    parser.add_argument("--list-voices", action="store_true", help="List available pyttsx3 voices and exit.")
    parser.add_argument("--repeat", type=int, default=1, help="Speak the text N times.")
    parser.add_argument("--gap", type=float, default=0.3, help="Seconds to wait between repeated speaks.")
    parser.add_argument("--reuse-engine", action="store_true", help="Reuse one pyttsx3 engine across repeats.")
    args = parser.parse_args()

    clear_settings_cache()
    settings = get_voice_settings()
    print("TTS direct check")
    print("================")
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Backend env file path: {settings.env_file_path}")
    print(f"TTS_ENABLED: {settings.tts_enabled}")
    print(f"TTS_ENGINE: {settings.tts_engine}")
    print(f"TTS_PLAYBACK_TARGET: {settings.tts_playback_target}")
    print(f"TTS_ENGINE_RECREATE_PER_TASK: {settings.tts_engine_recreate_per_task}")
    print(f"TTS_RATE: {settings.tts_rate}")
    print(f"TTS_VOLUME: {settings.tts_volume}")
    print(f"TTS_VOICE_NAME: {settings.tts_voice_name or '(default)'}")

    try:
        import pyttsx3
    except Exception as exc:
        print(f"pyttsx3 import failed: {type(exc).__name__}: {exc}")
        return 1
    print("pyttsx3 import: ok")

    if args.list_voices:
        pythoncom, com_initialized = _co_initialize()
        try:
            engine = pyttsx3.init()
            voices = list(engine.getProperty("voices") or [])
            print(f"voice count: {len(voices)}")
            for index, voice in enumerate(voices):
                info = _voice_info(voice)
                print(f"[{index}] id={info['id']} name={info['name']} languages={info['languages']}")
            _safe_stop(engine)
            return 0
        except Exception as exc:
            print(f"list voices failed: {type(exc).__name__}: {exc}")
            return 1
        finally:
            _co_uninitialize(pythoncom, com_initialized)

    repeat = max(1, args.repeat)
    print(f"repeat: {repeat}")
    print(f"gap: {args.gap}")
    print(f"engine mode: {'reuse-engine' if args.reuse_engine else 'recreate-per-task'}")
    if args.reuse_engine:
        return _speak_reusing_engine(pyttsx3, settings, args.text, repeat, args.gap)
    return _speak_recreating_engine(pyttsx3, settings, args.text, repeat, args.gap)


def _speak_recreating_engine(pyttsx3: Any, settings: Any, text: str, repeat: int, gap: float) -> int:
    failures = 0
    for index in range(1, repeat + 1):
        pythoncom, com_initialized = _co_initialize()
        engine = None
        try:
            print(f"[{index}/{repeat}] init started")
            engine = pyttsx3.init()
            print(f"[{index}/{repeat}] init finished")
            _configure_engine(engine, settings)
            print(f"[{index}/{repeat}] speak started: length={len(text)}")
            engine.say(text)
            print(f"[{index}/{repeat}] runAndWait started")
            engine.runAndWait()
            print(f"[{index}/{repeat}] runAndWait finished")
        except Exception as exc:
            failures += 1
            print(f"[{index}/{repeat}] speak failed: {type(exc).__name__}: {exc}")
        finally:
            _safe_stop(engine)
            engine = None
            _co_uninitialize(pythoncom, com_initialized)
        if index < repeat and gap > 0:
            time.sleep(gap)
    print(f"repeat finished: success={repeat - failures}, failures={failures}")
    return 0 if failures == 0 else 1


def _speak_reusing_engine(pyttsx3: Any, settings: Any, text: str, repeat: int, gap: float) -> int:
    pythoncom, com_initialized = _co_initialize()
    engine = None
    failures = 0
    try:
        print("reuse init started")
        engine = pyttsx3.init()
        print("reuse init finished")
        _configure_engine(engine, settings)
        for index in range(1, repeat + 1):
            try:
                print(f"[{index}/{repeat}] speak started: length={len(text)}")
                engine.say(text)
                print(f"[{index}/{repeat}] runAndWait started")
                engine.runAndWait()
                print(f"[{index}/{repeat}] runAndWait finished")
            except Exception as exc:
                failures += 1
                print(f"[{index}/{repeat}] speak failed: {type(exc).__name__}: {exc}")
            if index < repeat and gap > 0:
                time.sleep(gap)
    except Exception as exc:
        print(f"reuse engine init failed: {type(exc).__name__}: {exc}")
        return 1
    finally:
        _safe_stop(engine)
        engine = None
        _co_uninitialize(pythoncom, com_initialized)
    print(f"repeat finished: success={repeat - failures}, failures={failures}")
    return 0 if failures == 0 else 1


def _configure_engine(engine: Any, settings: Any) -> None:
    engine.setProperty("rate", settings.tts_rate)
    engine.setProperty("volume", settings.tts_volume)
    voices = list(engine.getProperty("voices") or [])
    print(f"voice count: {len(voices)}")
    selected = _find_voice(voices, settings.tts_voice_name.strip()) if settings.tts_voice_name.strip() else None
    if selected is not None:
        engine.setProperty("voice", selected.id)
    elif settings.tts_voice_name.strip():
        print("voice warning: configured TTS_VOICE_NAME not found, using default voice")
    current_id = engine.getProperty("voice")
    current = next((voice for voice in voices if getattr(voice, "id", None) == current_id), None) or selected
    print(f"current voice: {_voice_info(current, current_id)}")


def _co_initialize() -> tuple[Any, bool]:
    try:
        import pythoncom as imported_pythoncom  # type: ignore[import-not-found]

        imported_pythoncom.CoInitialize()
        print("pythoncom: CoInitialize ok")
        return imported_pythoncom, True
    except ImportError:
        print("pythoncom: unavailable, continuing without explicit COM initialization")
        return None, False


def _co_uninitialize(pythoncom: Any, com_initialized: bool) -> None:
    if not com_initialized or pythoncom is None:
        return
    try:
        pythoncom.CoUninitialize()
        print("pythoncom: CoUninitialize ok")
    except Exception as exc:
        print(f"pythoncom CoUninitialize warning: {type(exc).__name__}: {exc}")


def _safe_stop(engine: Any) -> None:
    if engine is None:
        return
    try:
        engine.stop()
    except Exception as exc:
        print(f"engine stop warning: {type(exc).__name__}: {exc}")


def _find_voice(voices: list[Any], configured: str) -> Any | None:
    for voice in voices:
        if getattr(voice, "id", None) == configured:
            return voice
    for voice in voices:
        if getattr(voice, "name", None) == configured:
            return voice
    lowered = configured.lower()
    for voice in voices:
        if lowered in str(getattr(voice, "name", "") or "").lower():
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


if __name__ == "__main__":
    raise SystemExit(main())
