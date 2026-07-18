from __future__ import annotations

from enum import StrEnum


class AudioEncoding(StrEnum):
    PCM_S16LE = "PCM_S16LE"
    WAV_PCM_S16LE = "WAV_PCM_S16LE"
    MP3 = "MP3"
    AAC = "AAC"
    OPUS = "OPUS"
    G711_MULAW = "G711_MULAW"
    G711_ALAW = "G711_ALAW"


class ProviderMode(StrEnum):
    DISABLED = "DISABLED"
    REPLAY = "REPLAY"
    LOCAL = "LOCAL"
    LIVE = "LIVE"


class SpeechOutcome(StrEnum):
    SUCCESS = "SUCCESS"
    NO_SPEECH = "NO_SPEECH"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    TRUNCATED = "TRUNCATED"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    UNSUPPORTED_LANGUAGE = "UNSUPPORTED_LANGUAGE"
    VALIDATION_ERROR = "VALIDATION_ERROR"


SUPPORTED_ENCODINGS = frozenset({AudioEncoding.PCM_S16LE, AudioEncoding.WAV_PCM_S16LE})
WAV_CONTENT_TYPES = frozenset({"audio/wav", "audio/x-wav", "audio/wave"})
PCM_CONTENT_TYPES = frozenset({"audio/l16", "audio/pcm", "application/octet-stream"})
