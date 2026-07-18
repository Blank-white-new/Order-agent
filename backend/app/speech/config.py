from __future__ import annotations

import os
from dataclasses import dataclass


TRUE_VALUES = {"1", "true", "yes", "on"}


def _boolean(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    return default if raw is None else raw.strip().casefold() in TRUE_VALUES


def _positive_int(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value < 1:
        raise ValueError(f"{name} must be positive")
    return value


def _probability(name: str, default: float) -> float:
    value = float(os.getenv(name, str(default)))
    if not 0 <= value <= 1:
        raise ValueError(f"{name} must be between 0 and 1")
    return value


@dataclass(frozen=True)
class SpeechSettings:
    app_env: str = "development"
    simulation_data_only: bool = True
    asr_provider: str = "disabled"
    tts_provider: str = "disabled"
    simulation_enabled: bool = False
    audio_retention_enabled: bool = False
    max_audio_bytes: int = 960_044
    min_duration_ms: int = 100
    max_duration_ms: int = 30_000
    supported_sample_rates_hz: tuple[int, ...] = (8_000, 16_000)
    confirm_threshold: float = 0.65
    handoff_threshold: float = 0.35
    no_speech_threshold: float = 0.90
    max_consecutive_low_confidence: int = 2

    def __post_init__(self) -> None:
        if self.audio_retention_enabled:
            raise ValueError("Phase 5 does not permit persistent audio retention")
        if self.min_duration_ms >= self.max_duration_ms:
            raise ValueError("Speech duration limits are invalid")
        if not 0 <= self.handoff_threshold <= self.confirm_threshold <= 1:
            raise ValueError("Speech confidence thresholds are invalid")

    @classmethod
    def from_env(cls, *, app_env: str | None = None, simulation_data_only: bool | None = None) -> "SpeechSettings":
        return cls(
            app_env=(app_env or os.getenv("APP_ENV", "development")).strip().casefold(),
            simulation_data_only=(
                _boolean("SIMULATION_DATA_ONLY", True)
                if simulation_data_only is None
                else simulation_data_only
            ),
            asr_provider=os.getenv("SPEECH_ASR_PROVIDER", "disabled").strip().casefold(),
            tts_provider=os.getenv("SPEECH_TTS_PROVIDER", "disabled").strip().casefold(),
            simulation_enabled=_boolean("SPEECH_SIMULATION_ENABLED", False),
            audio_retention_enabled=_boolean("SPEECH_AUDIO_RETENTION_ENABLED", False),
            max_audio_bytes=_positive_int("SPEECH_MAX_AUDIO_BYTES", 960_044),
            min_duration_ms=_positive_int("SPEECH_MIN_DURATION_MS", 100),
            max_duration_ms=_positive_int("SPEECH_MAX_DURATION_MS", 30_000),
            confirm_threshold=_probability("SPEECH_CONFIRM_THRESHOLD", 0.65),
            handoff_threshold=_probability("SPEECH_HANDOFF_THRESHOLD", 0.35),
            no_speech_threshold=_probability("SPEECH_NO_SPEECH_THRESHOLD", 0.90),
            max_consecutive_low_confidence=_positive_int(
                "SPEECH_MAX_CONSECUTIVE_LOW_CONFIDENCE", 2
            ),
        )

    @property
    def may_use_simulation(self) -> bool:
        return (
            self.app_env in {"development", "test"}
            and self.simulation_data_only
            and self.simulation_enabled
        )
