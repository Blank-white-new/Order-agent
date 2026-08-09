from __future__ import annotations

import os
import tempfile
from pathlib import Path


SENSITIVE_PROVIDER_VARIABLES = (
    "LLM_FALLBACK_API_KEY",
    "LLM_FALLBACK_BASE_URL",
    "LLM_FALLBACK_MODEL",
    "LLM_FALLBACK_PROVIDER",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL",
    "LLM_FALLBACK_REPLAY_FILE",
    "LLM_FALLBACK_SHADOW_SOURCE",
)


def force_offline_environment(label: str) -> None:
    """Fail closed before any backend import can read local provider settings."""
    os.environ.update(
        {
            "APP_ENV": "test",
            "SIMULATION_DATA_ONLY": "true",
            "LLM_FALLBACK_MODE": "disabled",
            "LLM_FALLBACK_ENABLED": "false",
            "LLM_FALLBACK_SPECULATIVE_ENABLED": "false",
            "ALLOW_LIVE_LLM": "false",
            "VOICE_ENABLED": "false",
            "TTS_ENABLED": "false",
            "SPEECH_AUDIO_RETENTION_ENABLED": "false",
            "BACKEND_ENV_FILE": str(
                Path(tempfile.gettempdir()) / f"{label}-{os.getpid()}-missing.env"
            ),
        }
    )
    for name in SENSITIVE_PROVIDER_VARIABLES:
        os.environ.pop(name, None)
