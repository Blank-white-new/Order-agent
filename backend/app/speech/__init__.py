"""Synthetic Phase 5 speech contracts and offline replay pipeline.

Replay providers validate repository fixtures.  They are not real ASR or TTS.
"""

from app.speech.contracts import (
    AsrCapabilities,
    AudioInput,
    SpeechRecognitionRequest,
    SpeechTurnResult,
    SynthesisEnvelope,
    SynthesisRequest,
    TranscriptEnvelope,
    TtsCapabilities,
)
from app.speech.formats import AudioEncoding, ProviderMode, SpeechOutcome

__all__ = [
    "AsrCapabilities",
    "AudioEncoding",
    "AudioInput",
    "ProviderMode",
    "SpeechOutcome",
    "SpeechRecognitionRequest",
    "SpeechTurnResult",
    "SynthesisEnvelope",
    "SynthesisRequest",
    "TranscriptEnvelope",
    "TtsCapabilities",
]
