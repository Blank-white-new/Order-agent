from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.voice.config import clear_settings_cache, get_voice_settings  # noqa: E402
from app.voice.status import evaluate_voice_status  # noqa: E402


def main() -> int:
    clear_settings_cache()
    settings = get_voice_settings()
    status = evaluate_voice_status(settings)

    print("Voice setup check")
    print("=================")
    print(f"Current working directory: {Path.cwd()}")
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Backend env file path: {settings.env_file_path}")
    print(f"Backend env file exists: {settings.env_file_exists}")
    print(f"VOICE_ENABLED: {settings.voice_enabled}")
    print(f"ASR_ENGINE: {settings.asr_engine}")
    print(f"VOSK_MODEL_PATH: {settings.vosk_model_path}")
    print(f"VOSK_MODEL_PATH exists: {status['modelPathExists']}")
    print(f"VOSK model looks valid: {status['modelLooksValid']}")
    print(f"vosk import available: {status['asrDependencyAvailable']}")
    print(f"pyttsx3 import available: {status['ttsDependencyAvailable']}")
    print(f"Expected canRecord: {status['canRecord']}")
    print(f"Expected canSpeak: {status['canSpeak']}")

    if status["canRecord"]:
        print("\nOK: voice recording should be available after restarting FastAPI.")
        return 0

    print("\nVoice recording is not ready. Next steps:")
    if not status["voiceEnabled"]:
        print("- Set VOICE_ENABLED=true in the backend .env file and restart FastAPI.")
    if not status["asrDependencyAvailable"]:
        print("- Install backend voice dependency: python -m pip install vosk")
    if not status["modelPathExists"]:
        print("- Download a Vosk Chinese model and extract it to models/asr/vosk-cn")
    elif not status["modelLooksValid"]:
        print("- VOSK_MODEL_PATH exists but does not look like the extracted Vosk model root.")
        print("  It should contain directories such as conf, am, graph, and optionally ivector.")
    if status["hints"]:
        print("\nStatus hints:")
        for hint in status["hints"]:
            print(f"- {hint}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
