from __future__ import annotations

import hashlib
from time import perf_counter
from uuid import uuid4

from app.speech.audio_normalizer import AudioNormalizer
from app.speech.audio_validator import AudioValidationResult, AudioValidator
from app.speech.config import SpeechSettings
from app.speech.contracts import (
    AudioInput,
    SpeechRecognitionRequest,
    SpeechTurnResult,
    SynthesisEnvelope,
    SynthesisRequest,
    TranscriptEnvelope,
)
from app.speech.errors import SpeechError, speech_error
from app.speech.formats import AudioEncoding, SpeechOutcome
from app.speech.provider_registry import SpeechProviderRegistry


FAILURE_OUTCOMES = {
    "NO_SPEECH_DETECTED": SpeechOutcome.NO_SPEECH,
    "SPEECH_TIMEOUT": SpeechOutcome.PROVIDER_TIMEOUT,
    "SPEECH_PROVIDER_FAILURE": SpeechOutcome.PROVIDER_ERROR,
    "SPEECH_LANGUAGE_UNSUPPORTED": SpeechOutcome.UNSUPPORTED_LANGUAGE,
    "AUDIO_TRUNCATED": SpeechOutcome.TRUNCATED,
}


class SpeechPipelineService:
    """The only Phase 5 audio entry point.

    Successful transcripts are always delegated to TextEntryService.  The
    speech layer never invokes an Orchestrator, repository, order service, or
    Handoff service directly.
    """

    def __init__(
        self,
        *,
        settings: SpeechSettings,
        registry: SpeechProviderRegistry,
        text_entry_service,
        validator: AudioValidator | None = None,
        normalizer: AudioNormalizer | None = None,
        audit_service=None,
    ) -> None:
        self.settings = settings
        self.registry = registry
        self.text_entry_service = text_entry_service
        self.validator = validator or AudioValidator(settings)
        self.normalizer = normalizer or AudioNormalizer(self.validator)
        self.audit_service = audit_service

    def _require_simulation(self, audio: AudioInput | None = None) -> None:
        if not self.settings.may_use_simulation:
            raise speech_error("SPEECH_SIMULATION_DISABLED")
        if audio is not None and (not audio.synthetic or not self.settings.simulation_data_only):
            raise speech_error("SPEECH_PROVIDER_NOT_ALLOWED")

    def transcribe(
        self,
        *,
        session_id: str,
        restaurant_code: str,
        branch_code: str,
        audio: AudioInput,
        locale_hint: str | None = None,
        trace_id: str | None = None,
    ) -> tuple[TranscriptEnvelope, AudioValidationResult, str]:
        self._require_simulation(audio)
        self.text_entry_service.ensure_session_context(
            session_id,
            restaurant_code=restaurant_code,
            branch_code=branch_code,
        )
        trace_id = trace_id or f"SIM-SP-{uuid4().hex}"
        if locale_hint is not None and locale_hint not in {
            "zh-CN",
            "yue-Hant-HK",
            "en-HK",
            "mixed",
        }:
            raise speech_error("SPEECH_LANGUAGE_UNSUPPORTED")
        validated = self.validator.validate(audio)
        # Exercise normalization explicitly; the result is intentionally not
        # persisted or serialized.
        normalized = self.normalizer.normalize(audio)
        if normalized.duration_ms != validated.duration_ms:
            raise speech_error("SPEECH_PROVIDER_FAILURE")
        provider = self.registry.get_asr()
        try:
            envelope = provider.transcribe(
                SpeechRecognitionRequest(
                    audio=audio,
                    locale_hint=locale_hint,
                    session_id=session_id,
                    restaurant_code=restaurant_code,
                    branch_code=branch_code,
                    trace_id=trace_id,
                )
            )
        except SpeechError:
            raise
        except Exception as exc:
            raise speech_error("SPEECH_PROVIDER_FAILURE") from exc
        if not envelope.synthetic or not envelope.transcript.strip():
            raise speech_error("TRANSCRIPT_EMPTY")
        if (
            envelope.no_speech_probability is not None
            and envelope.no_speech_probability >= self.settings.no_speech_threshold
        ):
            raise speech_error("NO_SPEECH_DETECTED")
        return envelope, validated, trace_id

    async def handle_audio_message(
        self,
        *,
        session_id: str,
        restaurant_code: str,
        branch_code: str,
        audio: AudioInput,
        locale_hint: str | None = None,
        idempotency_key: str | None = None,
        synthesize_response: bool = False,
        voice_id: str = "replay-neutral",
    ) -> SpeechTurnResult:
        trace_id = f"SIM-SP-{uuid4().hex}"
        audio_hash = hashlib.sha256(audio.payload).hexdigest()
        try:
            transcript, validated, trace_id = self.transcribe(
                session_id=session_id,
                restaurant_code=restaurant_code,
                branch_code=branch_code,
                audio=audio,
                locale_hint=locale_hint,
                trace_id=trace_id,
            )
        except SpeechError as exc:
            outcome = FAILURE_OUTCOMES.get(exc.code)
            if outcome is not None:
                # AUDIO_TRUNCATED can originate from either strict container
                # validation or a reviewed provider outcome.  Only the latter
                # advances non-text safety counters.
                try:
                    self.validator.validate(audio)
                except SpeechError:
                    outcome = None
            if outcome is None:
                # Invalid client declarations must never mask the stable
                # validation error with an audit-table constraint failure.
                if audio.sample_rate_hz > 0:
                    self._record_audit(
                        session_id=session_id,
                        restaurant_code=restaurant_code,
                        branch_code=branch_code,
                        direction="INPUT",
                        audio=audio,
                        trace_id=trace_id,
                        outcome=SpeechOutcome.VALIDATION_ERROR.value,
                        reason_code=exc.code,
                        audio_sha256=audio_hash,
                        duration_ms=None,
                    )
                raise
            text_started = perf_counter()
            text_result = await self.text_entry_service.handle_non_text_input_failure(
                session_id,
                exc.code,
                restaurant_code=restaurant_code,
                branch_code=branch_code,
                confidence_metadata={"overall_confidence": 0.0},
            )
            text_pipeline_ms = (perf_counter() - text_started) * 1000
            self._record_audit(
                session_id=session_id,
                restaurant_code=restaurant_code,
                branch_code=branch_code,
                direction="INPUT",
                audio=audio,
                trace_id=trace_id,
                outcome=outcome.value,
                reason_code=exc.code,
                audio_sha256=audio_hash,
                duration_ms=None,
                text_result=text_result,
            )
            return SpeechTurnResult(
                outcome=outcome,
                trace_id=trace_id,
                text_result=text_result,
                transcript=None,
                synthesis=None,
                error_code=exc.code,
                audio_sha256=audio_hash,
                text_pipeline_ms=text_pipeline_ms,
            )

        confidence_metadata = self._confidence_mapping(transcript)
        text_started = perf_counter()
        text_result = await self.text_entry_service.handle_text_message(
            session_id,
            transcript.transcript,
            restaurant_code=restaurant_code,
            branch_code=branch_code,
            idempotency_key=idempotency_key,
            confidence_metadata=confidence_metadata,
            locale_hint=locale_hint,
        )
        text_pipeline_ms = (perf_counter() - text_started) * 1000
        outcome = (
            SpeechOutcome.LOW_CONFIDENCE
            if self._effective_confidence(transcript) < self.settings.confirm_threshold
            else SpeechOutcome.SUCCESS
        )
        synthesis = None
        tts_error_code = None
        if synthesize_response:
            try:
                synthesis = self.synthesize(
                    text=text_result["response"],
                    locale=text_result.get("response_locale", "zh-CN"),
                    voice_id=voice_id,
                    trace_id=trace_id,
                )
            except SpeechError as exc:
                # TTS is output-only.  Its failure must not roll back or advance
                # the already-authoritative text/order result.
                tts_error_code = exc.code
        self._record_audit(
            session_id=session_id,
            restaurant_code=restaurant_code,
            branch_code=branch_code,
            direction="INPUT",
            audio=audio,
            trace_id=trace_id,
            outcome=outcome.value,
            reason_code=None,
            audio_sha256=audio_hash,
            duration_ms=validated.duration_ms,
            transcript=transcript,
            text_result=text_result,
        )
        return SpeechTurnResult(
            outcome=outcome,
            trace_id=trace_id,
            text_result=text_result,
            transcript=transcript,
            synthesis=synthesis,
            tts_error_code=tts_error_code,
            audio_sha256=audio_hash,
            duration_ms=validated.duration_ms,
            text_pipeline_ms=text_pipeline_ms,
        )

    def synthesize(
        self,
        *,
        text: str,
        locale: str,
        voice_id: str = "replay-neutral",
        output_encoding: AudioEncoding = AudioEncoding.WAV_PCM_S16LE,
        sample_rate_hz: int = 16_000,
        trace_id: str | None = None,
        session_id: str | None = None,
        restaurant_code: str | None = None,
        branch_code: str | None = None,
    ) -> SynthesisEnvelope:
        self._require_simulation()
        if locale not in {"zh-CN", "yue-Hant-HK", "en-HK"}:
            raise speech_error("SPEECH_LANGUAGE_UNSUPPORTED")
        if output_encoding != AudioEncoding.WAV_PCM_S16LE:
            raise speech_error("AUDIO_ENCODING_UNSUPPORTED")
        trace_id = trace_id or f"SIM-TTS-{uuid4().hex}"
        provider = self.registry.get_tts()
        try:
            envelope = provider.synthesize(
                SynthesisRequest(
                    text=text,
                    locale=locale,
                    voice_id=voice_id,
                    output_encoding=output_encoding,
                    sample_rate_hz=sample_rate_hz,
                    trace_id=trace_id,
                    synthetic=True,
                )
            )
        except SpeechError:
            raise
        except Exception as exc:
            raise speech_error("SPEECH_PROVIDER_FAILURE") from exc
        self.validator.validate(
            output_audio := AudioInput(
                payload=envelope.payload,
                content_type=envelope.content_type,
                encoding=envelope.encoding,
                sample_rate_hz=envelope.sample_rate_hz,
                channels=1,
                sample_width_bytes=2,
                synthetic=True,
            )
        )
        if session_id and restaurant_code and branch_code:
            self.text_entry_service.ensure_session_context(
                session_id,
                restaurant_code=restaurant_code,
                branch_code=branch_code,
            )
            self._record_audit(
                session_id=session_id,
                restaurant_code=restaurant_code,
                branch_code=branch_code,
                direction="OUTPUT",
                audio=output_audio,
                trace_id=trace_id,
                outcome=SpeechOutcome.SUCCESS.value,
                reason_code=None,
                audio_sha256=hashlib.sha256(envelope.payload).hexdigest(),
                duration_ms=envelope.duration_ms,
            )
        return envelope

    def _record_audit(self, **metadata) -> None:
        if self.audit_service is not None:
            self.audit_service.record(**metadata)

    @staticmethod
    def _effective_confidence(transcript: TranscriptEnvelope) -> float:
        values = [
            value
            for key, value in transcript.confidence_metadata.items()
            if key.endswith("_confidence") and isinstance(value, (int, float))
        ]
        if transcript.confidence is not None:
            values.append(transcript.confidence)
        return min(values) if values else 0.0

    @staticmethod
    def _confidence_mapping(transcript: TranscriptEnvelope) -> dict:
        allowed = {
            "intent_confidence",
            "item_confidence",
            "quantity_confidence",
            "modifier_confidence",
            "address_confidence",
            "phone_confidence",
            "overall_confidence",
            "contradictory_fields",
        }
        metadata = {
            key: value
            for key, value in transcript.confidence_metadata.items()
            if key in allowed
        }
        metadata.setdefault("overall_confidence", transcript.confidence)
        return metadata
