from __future__ import annotations

from dataclasses import dataclass

from app.speech.audio_validator import AudioValidationResult, AudioValidator
from app.speech.contracts import AudioInput


@dataclass(frozen=True)
class NormalizedAudio:
    pcm_s16le: bytes
    sample_rate_hz: int
    channels: int
    sample_width_bytes: int
    frame_count: int
    duration_ms: int


class AudioNormalizer:
    """Deterministically extracts supported PCM; it never transcodes or resamples."""

    def __init__(self, validator: AudioValidator) -> None:
        self.validator = validator

    def normalize(self, audio: AudioInput) -> NormalizedAudio:
        validated: AudioValidationResult = self.validator.validate(audio)
        return NormalizedAudio(
            pcm_s16le=validated.pcm_payload,
            sample_rate_hz=validated.sample_rate_hz,
            channels=validated.channels,
            sample_width_bytes=validated.sample_width_bytes,
            frame_count=validated.frame_count,
            duration_ms=validated.duration_ms,
        )
