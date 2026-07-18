from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.speech.formats import AudioEncoding, ProviderMode, SpeechOutcome


@dataclass(frozen=True)
class AudioInput:
    payload: bytes
    content_type: str
    encoding: AudioEncoding
    sample_rate_hz: int
    channels: int
    sample_width_bytes: int
    fixture_id: str | None = None
    synthetic: bool = True

    def serializable(self) -> dict[str, Any]:
        return {
            "contentType": self.content_type,
            "encoding": self.encoding.value,
            "sampleRateHz": self.sample_rate_hz,
            "channels": self.channels,
            "sampleWidthBytes": self.sample_width_bytes,
            "fixtureId": self.fixture_id,
            "synthetic": self.synthetic,
            "payloadBytes": len(self.payload),
        }


@dataclass(frozen=True)
class SpeechRecognitionRequest:
    audio: AudioInput
    locale_hint: str | None
    session_id: str
    restaurant_code: str
    branch_code: str
    trace_id: str


@dataclass(frozen=True)
class TranscriptSegment:
    start_ms: int
    end_ms: int
    confidence: float | None = None


@dataclass(frozen=True)
class TranscriptEnvelope:
    transcript: str
    provider_name: str
    provider_mode: ProviderMode
    provider_request_id: str | None
    confidence: float | None
    locale: str | None
    duration_ms: int
    no_speech_probability: float | None
    segments: tuple[TranscriptSegment, ...] = ()
    synthetic: bool = True
    confidence_metadata: dict[str, Any] = field(default_factory=dict)

    def serializable(self, *, include_transcript: bool = False) -> dict[str, Any]:
        payload = {
            "providerName": self.provider_name,
            "providerMode": self.provider_mode.value,
            "providerRequestId": self.provider_request_id,
            "confidence": self.confidence,
            "locale": self.locale,
            "durationMs": self.duration_ms,
            "noSpeechProbability": self.no_speech_probability,
            "segments": [asdict(segment) for segment in self.segments],
            "synthetic": self.synthetic,
        }
        if include_transcript:
            payload["transcript"] = self.transcript
        return payload


@dataclass(frozen=True)
class SynthesisRequest:
    text: str
    locale: str
    voice_id: str
    output_encoding: AudioEncoding
    sample_rate_hz: int
    trace_id: str
    synthetic: bool = True


@dataclass(frozen=True)
class SynthesisEnvelope:
    payload: bytes
    provider_name: str
    provider_mode: ProviderMode
    content_type: str
    encoding: AudioEncoding
    sample_rate_hz: int
    duration_ms: int
    synthetic: bool = True

    def serializable(self) -> dict[str, Any]:
        return {
            "providerName": self.provider_name,
            "providerMode": self.provider_mode.value,
            "contentType": self.content_type,
            "encoding": self.encoding.value,
            "sampleRateHz": self.sample_rate_hz,
            "durationMs": self.duration_ms,
            "payloadBytes": len(self.payload),
            "synthetic": self.synthetic,
        }


@dataclass(frozen=True)
class AsrCapabilities:
    provider_name: str
    provider_mode: ProviderMode
    locales: tuple[str, ...]
    encodings: tuple[AudioEncoding, ...]
    sample_rates_hz: tuple[int, ...]
    streaming: bool
    synthetic: bool
    requires_network: bool
    production_allowed: bool

    def serializable(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "provider_mode": self.provider_mode.value,
            "encodings": [encoding.value for encoding in self.encodings],
        }


@dataclass(frozen=True)
class TtsCapabilities(AsrCapabilities):
    voice_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class SpeechTurnResult:
    outcome: SpeechOutcome
    trace_id: str
    text_result: dict[str, Any] | None
    transcript: TranscriptEnvelope | None
    synthesis: SynthesisEnvelope | None
    error_code: str | None = None
    tts_error_code: str | None = None
    audio_sha256: str | None = None
    duration_ms: int | None = None
    text_pipeline_ms: float | None = None

    def serializable(
        self,
        *,
        include_transcript: bool = False,
        include_audio: bool = False,
    ) -> dict[str, Any]:
        text_result = self.text_result or {}
        payload: dict[str, Any] = {
            "outcome": self.outcome.value,
            "traceId": self.trace_id,
            "errorCode": self.error_code,
            "ttsErrorCode": self.tts_error_code,
            "audioSha256": self.audio_sha256,
            "durationMs": self.duration_ms,
            "timing": {
                "textPipelineMs": self.text_pipeline_ms,
            },
            "simulation": True,
            "providerMode": ProviderMode.REPLAY.value,
            "realSpeechRecognition": False,
            "realSpeechSynthesis": False,
            "response": text_result.get("response"),
            "state": text_result.get("state"),
            "trace": text_result.get("trace"),
            "lifecycleStatus": text_result.get("lifecycle_status"),
            "merchantStatus": text_result.get("merchant_status"),
            "detectedLocale": text_result.get("detected_locale"),
            "responseLocale": text_result.get("response_locale"),
            "safetyClassification": getattr(text_result.get("raw_state"), "safety_classification", None),
            "handoffStatus": getattr(text_result.get("raw_state"), "handoff_status", None),
            "transcriptMetadata": self.transcript.serializable(
                include_transcript=include_transcript
            ) if self.transcript else None,
            "synthesisMetadata": self.synthesis.serializable() if self.synthesis else None,
        }
        if include_audio and self.synthesis:
            payload["audio"] = self.synthesis.payload
        return payload
