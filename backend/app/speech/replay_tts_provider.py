from __future__ import annotations

import hashlib
from pathlib import Path

from app.speech.contracts import SynthesisEnvelope, SynthesisRequest, TtsCapabilities
from app.speech.errors import speech_error
from app.speech.formats import AudioEncoding, ProviderMode
from app.speech.invocation_observer import ProviderInvocation, ProviderInvocationObserver
from app.speech.manifest import load_jsonl, safe_repository_path


class ReplayTtsProvider:
    """Returns pre-reviewed synthetic WAV fixtures; it does not synthesize speech."""

    def __init__(
        self,
        manifest_path: Path,
        repository_root: Path,
        invocation_observer: ProviderInvocationObserver | None = None,
    ) -> None:
        self.repository_root = repository_root.resolve()
        self._invocation_observer = invocation_observer
        self._entries: dict[tuple[str, str, str, str, int], dict] = {}
        for row in load_jsonl(manifest_path):
            key = (
                str(row.get("textSha256", "")).casefold(),
                str(row.get("locale", "")),
                str(row.get("voiceId", "")),
                str(row.get("encoding", "")),
                int(row.get("sampleRateHz", 0)),
            )
            self._entries[key] = row

    @property
    def name(self) -> str:
        return "replay"

    def capabilities(self) -> TtsCapabilities:
        return TtsCapabilities(
            provider_name=self.name,
            provider_mode=ProviderMode.REPLAY,
            locales=("zh-CN", "yue-Hant-HK", "en-HK"),
            encodings=(AudioEncoding.WAV_PCM_S16LE,),
            sample_rates_hz=(16_000,),
            streaming=False,
            synthetic=True,
            requires_network=False,
            production_allowed=False,
            voice_ids=("replay-neutral",),
        )

    def synthesize(self, request: SynthesisRequest) -> SynthesisEnvelope:
        capabilities = self.capabilities()
        invocation = ProviderInvocation(
            provider_name=self.name,
            provider_mode=capabilities.provider_mode,
            requires_network=capabilities.requires_network,
            operation="synthesize",
        )
        try:
            result = self._synthesize(request)
            invocation.success = True
            return result
        except Exception as exc:
            invocation.error_code = getattr(exc, "code", "SPEECH_PROVIDER_FAILURE")
            raise
        finally:
            if self._invocation_observer is not None:
                self._invocation_observer.record(invocation)

    def _synthesize(self, request: SynthesisRequest) -> SynthesisEnvelope:
        if not request.synthetic or not request.text.strip():
            raise speech_error("TTS_FIXTURE_NOT_FOUND")
        text_hash = hashlib.sha256(request.text.encode("utf-8")).hexdigest()
        key = (
            text_hash,
            request.locale,
            request.voice_id,
            request.output_encoding.value,
            request.sample_rate_hz,
        )
        entry = self._entries.get(key)
        if entry is None:
            raise speech_error("TTS_FIXTURE_NOT_FOUND")
        path = safe_repository_path(self.repository_root, str(entry.get("audioPath", "")))
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise speech_error("TTS_FIXTURE_NOT_FOUND") from exc
        if hashlib.sha256(payload).hexdigest() != str(entry.get("sha256", "")).casefold():
            raise speech_error("SPEECH_FIXTURE_HASH_MISMATCH")
        return SynthesisEnvelope(
            payload=payload,
            provider_name=self.name,
            provider_mode=ProviderMode.REPLAY,
            content_type="audio/wav",
            encoding=AudioEncoding.WAV_PCM_S16LE,
            sample_rate_hz=request.sample_rate_hz,
            duration_ms=int(entry.get("durationMs", 0)),
            synthetic=True,
        )
