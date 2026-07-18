from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.speech.config import SpeechSettings
from app.speech.contracts import AudioInput, SpeechRecognitionRequest, SynthesisRequest
from app.speech.errors import SpeechError
from app.speech.formats import AudioEncoding, ProviderMode
from app.speech.provider_registry import SpeechProviderRegistry
from app.speech.replay_asr_provider import ReplayAsrProvider
from app.speech.replay_tts_provider import ReplayTtsProvider


ROOT = Path(__file__).resolve().parents[3]
ASR_MANIFEST = ROOT / "evaluation" / "audio" / "manifests" / "phase5_asr_manifest.jsonl"
TTS_MANIFEST = ROOT / "evaluation" / "audio" / "manifests" / "phase5_tts_manifest.jsonl"


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_replay_asr_requires_fixture_id_and_hash():
    provider = ReplayAsrProvider(ASR_MANIFEST)
    row = next(row for row in rows(ASR_MANIFEST) if row["outcome"] == "SUCCESS")
    payload = (ROOT / row["audioPath"]).read_bytes()
    request = SpeechRecognitionRequest(
        audio=AudioInput(
            payload=payload,
            content_type="audio/wav",
            encoding=AudioEncoding.WAV_PCM_S16LE,
            sample_rate_hz=16_000,
            channels=1,
            sample_width_bytes=2,
            fixture_id=row["fixtureId"],
            synthetic=True,
        ),
        locale_hint=None,
        session_id="provider-test",
        restaurant_code="hk-sim-restaurant-a",
        branch_code="central",
        trace_id="SIM-TRACE-PROVIDER",
    )
    result = provider.transcribe(request)
    assert result.transcript == row["transcript"]
    assert result.provider_mode == ProviderMode.REPLAY
    assert result.synthetic is True
    tampered = request.audio.payload + b"x"
    bad_request = SpeechRecognitionRequest(
        **{
            **request.__dict__,
            "audio": AudioInput(**{**request.audio.__dict__, "payload": tampered}),
        }
    )
    with pytest.raises(SpeechError, match="SPEECH_FIXTURE_HASH_MISMATCH"):
        provider.transcribe(bad_request)
    wrong_metadata = SpeechRecognitionRequest(
        **{
            **request.__dict__,
            "audio": AudioInput(
                **{
                    **request.audio.__dict__,
                    "sample_rate_hz": 8_000,
                }
            ),
        }
    )
    with pytest.raises(SpeechError) as raised:
        provider.transcribe(wrong_metadata)
    assert raised.value.code == "SPEECH_FIXTURE_HASH_MISMATCH"


def test_replay_asr_maps_reviewed_outcomes():
    provider = ReplayAsrProvider(ASR_MANIFEST)
    expected = {
        "NO_SPEECH": "NO_SPEECH_DETECTED",
        "PROVIDER_TIMEOUT": "SPEECH_TIMEOUT",
        "PROVIDER_ERROR": "SPEECH_PROVIDER_FAILURE",
        "UNSUPPORTED_LANGUAGE": "SPEECH_LANGUAGE_UNSUPPORTED",
        "TRUNCATED": "AUDIO_TRUNCATED",
    }
    manifest = rows(ASR_MANIFEST)
    for outcome, code in expected.items():
        row = next(row for row in manifest if row["outcome"] == outcome)
        payload = (ROOT / row["audioPath"]).read_bytes()
        request = SpeechRecognitionRequest(
            audio=AudioInput(payload, "audio/wav", AudioEncoding.WAV_PCM_S16LE, 16_000, 1, 2, row["fixtureId"], True),
            locale_hint=None,
            session_id="provider-outcome",
            restaurant_code="hk-sim-restaurant-a",
            branch_code="central",
            trace_id="SIM-TRACE-OUTCOME",
        )
        with pytest.raises(SpeechError) as raised:
            provider.transcribe(request)
        assert raised.value.code == code


def test_replay_tts_matches_text_hash_and_audio_hash():
    provider = ReplayTtsProvider(TTS_MANIFEST, ROOT)
    row = rows(TTS_MANIFEST)[0]
    request = SynthesisRequest(
        text=row["text"],
        locale=row["locale"],
        voice_id=row["voiceId"],
        output_encoding=AudioEncoding.WAV_PCM_S16LE,
        sample_rate_hz=row["sampleRateHz"],
        trace_id="SIM-TTS-TEST",
        synthetic=True,
    )
    result = provider.synthesize(request)
    assert hashlib.sha256(result.payload).hexdigest() == row["sha256"]
    assert result.provider_mode == ProviderMode.REPLAY
    with pytest.raises(SpeechError) as raised:
        provider.synthesize(SynthesisRequest(**{**request.__dict__, "text": "not catalogued"}))
    assert raised.value.code == "TTS_FIXTURE_NOT_FOUND"


def test_registry_fails_closed_and_blocks_replay_in_production():
    provider = ReplayAsrProvider(ASR_MANIFEST)
    disabled = SpeechProviderRegistry(SpeechSettings(app_env="test"), asr_providers=(provider,))
    with pytest.raises(SpeechError) as raised:
        disabled.get_asr()
    assert raised.value.code == "SPEECH_PROVIDER_DISABLED"
    production = SpeechProviderRegistry(
        SpeechSettings(app_env="production", asr_provider="replay"),
        asr_providers=(provider,),
    )
    with pytest.raises(SpeechError) as raised:
        production.get_asr()
    assert raised.value.code == "SPEECH_PROVIDER_NOT_ALLOWED"
