from __future__ import annotations

from typing import Protocol

from app.speech.contracts import (
    AsrCapabilities,
    SpeechRecognitionRequest,
    SynthesisEnvelope,
    SynthesisRequest,
    TranscriptEnvelope,
    TtsCapabilities,
)


class AsrProvider(Protocol):
    @property
    def name(self) -> str: ...

    def capabilities(self) -> AsrCapabilities: ...

    def transcribe(self, request: SpeechRecognitionRequest) -> TranscriptEnvelope: ...


class TtsProvider(Protocol):
    @property
    def name(self) -> str: ...

    def capabilities(self) -> TtsCapabilities: ...

    def synthesize(self, request: SynthesisRequest) -> SynthesisEnvelope: ...
