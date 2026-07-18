from __future__ import annotations

import hashlib
from pathlib import Path

from app.speech.contracts import (
    AsrCapabilities,
    SpeechRecognitionRequest,
    TranscriptEnvelope,
    TranscriptSegment,
)
from app.speech.errors import speech_error
from app.speech.formats import AudioEncoding, ProviderMode
from app.speech.manifest import load_jsonl, safe_repository_path


class ReplayAsrProvider:
    """Offline fixture replay.  This class performs no speech recognition."""

    def __init__(self, manifest_path: Path, repository_root: Path | None = None) -> None:
        self._repository_root = (repository_root or manifest_path.resolve().parents[3]).resolve()
        self._entries = {
            str(row.get("fixtureId")): row
            for row in load_jsonl(manifest_path)
            if row.get("fixtureId")
        }

    def list_fixtures(self) -> list[dict]:
        return [
            {
                "fixtureId": fixture_id,
                "locale": entry.get("locale"),
                "outcome": entry.get("outcome"),
                "contentType": entry.get("contentType", "audio/wav"),
                "encoding": entry.get("encoding", "WAV_PCM_S16LE"),
                "sampleRateHz": int(entry.get("sampleRateHz", 16000)),
                "channels": int(entry.get("channels", 1)),
                "sampleWidthBytes": int(entry.get("sampleWidthBytes", 2)),
                "synthetic": True,
            }
            for fixture_id, entry in sorted(self._entries.items())
        ]

    def fixture_payload(self, fixture_id: str) -> tuple[bytes, str]:
        entry = self._entries.get(fixture_id)
        if entry is None:
            raise speech_error("SPEECH_FIXTURE_NOT_FOUND")
        path = safe_repository_path(self._repository_root, str(entry.get("audioPath", "")))
        try:
            return path.read_bytes(), str(entry.get("contentType", "audio/wav"))
        except OSError as exc:
            raise speech_error("SPEECH_FIXTURE_NOT_FOUND") from exc

    @property
    def name(self) -> str:
        return "replay"

    def capabilities(self) -> AsrCapabilities:
        return AsrCapabilities(
            provider_name=self.name,
            provider_mode=ProviderMode.REPLAY,
            locales=("zh-CN", "yue-Hant-HK", "en-HK", "mixed"),
            encodings=(AudioEncoding.PCM_S16LE, AudioEncoding.WAV_PCM_S16LE),
            sample_rates_hz=(8_000, 16_000),
            streaming=False,
            synthetic=True,
            requires_network=False,
            production_allowed=False,
        )

    def transcribe(self, request: SpeechRecognitionRequest) -> TranscriptEnvelope:
        fixture_id = request.audio.fixture_id
        if not request.audio.synthetic or not fixture_id:
            raise speech_error("SPEECH_FIXTURE_NOT_FOUND")
        entry = self._entries.get(fixture_id)
        if entry is None:
            raise speech_error("SPEECH_FIXTURE_NOT_FOUND")
        actual_hash = hashlib.sha256(request.audio.payload).hexdigest()
        if actual_hash != str(entry.get("sha256", "")).casefold():
            raise speech_error("SPEECH_FIXTURE_HASH_MISMATCH")
        expected_metadata = (
            str(entry.get("contentType", "")).casefold(),
            str(entry.get("encoding", "")),
            int(entry.get("sampleRateHz", 0)),
            int(entry.get("channels", 0)),
            int(entry.get("sampleWidthBytes", 0)),
        )
        actual_metadata = (
            request.audio.content_type.split(";", 1)[0].strip().casefold(),
            request.audio.encoding.value,
            request.audio.sample_rate_hz,
            request.audio.channels,
            request.audio.sample_width_bytes,
        )
        if actual_metadata != expected_metadata:
            raise speech_error("SPEECH_FIXTURE_HASH_MISMATCH")

        outcome = str(entry.get("outcome", "SUCCESS")).upper()
        if outcome == "NO_SPEECH":
            raise speech_error("NO_SPEECH_DETECTED")
        if outcome == "PROVIDER_TIMEOUT":
            raise speech_error("SPEECH_TIMEOUT")
        if outcome == "PROVIDER_ERROR":
            raise speech_error("SPEECH_PROVIDER_FAILURE")
        if outcome == "UNSUPPORTED_LANGUAGE":
            raise speech_error("SPEECH_LANGUAGE_UNSUPPORTED")
        if outcome == "TRUNCATED":
            raise speech_error("AUDIO_TRUNCATED")
        if outcome not in {"SUCCESS", "LOW_CONFIDENCE"}:
            raise speech_error("SPEECH_PROVIDER_FAILURE")

        transcript = str(entry.get("transcript", "")).strip()
        if not transcript:
            raise speech_error("TRANSCRIPT_EMPTY")
        confidence = entry.get("confidence")
        if confidence is not None:
            confidence = float(confidence)
            if not 0 <= confidence <= 1:
                raise speech_error("SPEECH_PROVIDER_FAILURE")
        duration_ms = int(entry.get("durationMs", 0))
        segments = tuple(
            TranscriptSegment(
                start_ms=int(segment.get("startMs", 0)),
                end_ms=int(segment.get("endMs", duration_ms)),
                confidence=(
                    None if segment.get("confidence") is None else float(segment["confidence"])
                ),
            )
            for segment in entry.get("segments", [])
        )
        metadata = dict(entry.get("confidenceMetadata") or {})
        if confidence is not None:
            metadata.setdefault("overall_confidence", confidence)
        return TranscriptEnvelope(
            transcript=transcript,
            provider_name=self.name,
            provider_mode=ProviderMode.REPLAY,
            provider_request_id=f"REPLAY-{fixture_id}",
            confidence=confidence,
            locale=entry.get("locale"),
            duration_ms=duration_ms,
            no_speech_probability=(
                None
                if entry.get("noSpeechProbability") is None
                else float(entry["noSpeechProbability"])
            ),
            segments=segments,
            synthetic=True,
            confidence_metadata=metadata,
        )
