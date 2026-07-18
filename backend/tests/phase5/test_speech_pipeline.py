from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest

from app.speech.contracts import AudioInput
from app.speech.errors import SpeechError
from app.speech.formats import AudioEncoding, SpeechOutcome


ROOT = Path(__file__).resolve().parents[3]
DATASET = ROOT / "evaluation" / "phase5_speech_pipeline.jsonl"


def scenarios() -> list[dict]:
    return [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines()]


def scenario(locale: str, category: str) -> dict:
    return next(
        row for row in scenarios()
        if row["locale"] == locale and row["semanticCategory"] == category
    )


def audio(row: dict) -> AudioInput:
    return AudioInput(
        payload=(ROOT / row["audioPath"]).read_bytes(),
        content_type=row["contentType"],
        encoding=AudioEncoding(row["encoding"]),
        sample_rate_hz=row["sampleRateHz"],
        channels=row["channels"],
        sample_width_bytes=row["sampleWidthBytes"],
        fixture_id=row["fixtureId"],
        synthetic=True,
    )


def run(phase5, row: dict):
    session_id = f"phase5-{uuid4().hex}"
    for setup in row["setupInputs"]:
        asyncio.run(
            phase5.text_entry.handle_text_message(
                session_id,
                setup,
                restaurant_code="hk-sim-restaurant-a",
                branch_code="central",
            )
        )
    before = phase5.store.get(session_id, "hk-sim-restaurant-a", "central").serializable()
    result = asyncio.run(
        phase5.pipeline.handle_audio_message(
            session_id=session_id,
            restaurant_code="hk-sim-restaurant-a",
            branch_code="central",
            audio=audio(row),
        )
    )
    after = phase5.store.get(session_id, "hk-sim-restaurant-a", "central").serializable()
    return session_id, before, result, after


@pytest.mark.parametrize("locale", ["zh-CN", "yue-Hant-HK", "en-HK", "mixed"])
def test_successful_audio_uses_canonical_text_entry_path(phase5, locale):
    row = scenario(locale, "add1")
    _session, before, result, after = run(phase5, row)
    assert result.outcome == SpeechOutcome.SUCCESS
    assert result.transcript.transcript == row["expectedTranscript"]
    assert result.text_result["trace"]["executionPath"] == "CANONICAL_MULTILINGUAL"
    assert result.text_result["trace"]["multilingual"]["canonicalIntent"] == "ADD_ITEM"
    assert before["current_order"] != after["current_order"]
    assert after["merchant_status"] == "NOT_INTEGRATED"


@pytest.mark.parametrize("category", ["question_add", "human", "allergy", "cross_tenant"])
def test_safety_and_questions_preserve_phase3_priority(phase5, category):
    row = scenario("zh-CN", category)
    _session, before, result, after = run(phase5, row)
    assert before["current_order"] == after["current_order"]
    assert after["safety_classification"] == row["expectedClassification"]
    assert after["merchant_status"] == "NOT_INTEGRATED"


@pytest.mark.parametrize(
    ("category", "outcome", "error"),
    [
        ("no_speech", SpeechOutcome.NO_SPEECH, "NO_SPEECH_DETECTED"),
        ("low_confidence", SpeechOutcome.LOW_CONFIDENCE, None),
        ("provider_timeout", SpeechOutcome.PROVIDER_TIMEOUT, "SPEECH_TIMEOUT"),
        ("provider_error", SpeechOutcome.PROVIDER_ERROR, "SPEECH_PROVIDER_FAILURE"),
        ("unsupported_language", SpeechOutcome.UNSUPPORTED_LANGUAGE, "SPEECH_LANGUAGE_UNSUPPORTED"),
    ],
)
def test_failure_and_low_confidence_paths_do_not_mutate_orders(phase5, category, outcome, error):
    row = scenario("en-HK", category)
    _session, before, result, after = run(phase5, row)
    assert result.outcome == outcome
    assert result.error_code == error
    assert before["current_order"] == after["current_order"]
    assert after["merchant_status"] == "NOT_INTEGRATED"
    assert after["safety_classification"] in {"CONFIRM", "HANDOFF"}


def test_hash_mismatch_fails_before_text_entry_mutation(phase5):
    row = scenario("mixed", "hash_mismatch")
    session_id = f"phase5-{uuid4().hex}"
    before = phase5.store.get(session_id, "hk-sim-restaurant-a", "central").serializable()
    with pytest.raises(SpeechError) as raised:
        asyncio.run(
            phase5.pipeline.handle_audio_message(
                session_id=session_id,
                restaurant_code="hk-sim-restaurant-a",
                branch_code="central",
                audio=audio(row),
            )
        )
    assert raised.value.code == "SPEECH_FIXTURE_HASH_MISMATCH"
    after = phase5.store.get(session_id, "hk-sim-restaurant-a", "central").serializable()
    assert before["current_order"] == after["current_order"]


def test_invalid_zero_sample_rate_returns_stable_error_without_audit_masking(phase5):
    row = scenario("zh-CN", "add1")
    item = audio(row)
    invalid = AudioInput(
        payload=item.payload,
        content_type=item.content_type,
        encoding=item.encoding,
        sample_rate_hz=0,
        channels=item.channels,
        sample_width_bytes=item.sample_width_bytes,
        fixture_id=item.fixture_id,
        synthetic=True,
    )
    with pytest.raises(SpeechError) as raised:
        asyncio.run(
            phase5.pipeline.handle_audio_message(
                session_id=f"phase5-zero-rate-{uuid4().hex}",
                restaurant_code="hk-sim-restaurant-a",
                branch_code="central",
                audio=invalid,
            )
        )
    assert raised.value.code == "AUDIO_SAMPLE_RATE_UNSUPPORTED"


def test_repeated_no_speech_uses_text_entry_owned_handoff(phase5):
    row = scenario("zh-CN", "no_speech")
    session_id = f"phase5-{uuid4().hex}"
    first = asyncio.run(
        phase5.pipeline.handle_audio_message(
            session_id=session_id,
            restaurant_code="hk-sim-restaurant-a",
            branch_code="central",
            audio=audio(row),
        )
    )
    second = asyncio.run(
        phase5.pipeline.handle_audio_message(
            session_id=session_id,
            restaurant_code="hk-sim-restaurant-a",
            branch_code="central",
            audio=audio(row),
        )
    )
    assert first.text_result["raw_state"].safety_classification == "CONFIRM"
    assert second.text_result["raw_state"].safety_classification == "HANDOFF"
    assert second.text_result["raw_state"].handoff_status in {"REQUESTED", "PENDING"}


def test_tts_failure_does_not_change_authoritative_order_result(phase5):
    row = scenario("zh-CN", "add1")
    session_id = f"phase5-{uuid4().hex}"
    result = asyncio.run(
        phase5.pipeline.handle_audio_message(
            session_id=session_id,
            restaurant_code="hk-sim-restaurant-a",
            branch_code="central",
            audio=audio(row),
            synthesize_response=True,
        )
    )
    assert result.outcome == SpeechOutcome.SUCCESS
    assert result.tts_error_code == "TTS_FIXTURE_NOT_FOUND"
    state = phase5.store.get(session_id, "hk-sim-restaurant-a", "central")
    assert len(state.current_order) == 1
