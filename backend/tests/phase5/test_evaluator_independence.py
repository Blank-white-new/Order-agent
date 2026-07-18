from __future__ import annotations

import asyncio
import json
import socket
from pathlib import Path
from uuid import uuid4

from app.speech.contracts import AudioInput
from app.speech.formats import AudioEncoding


ROOT = Path(__file__).resolve().parents[3]
DATASET = ROOT / "evaluation" / "phase5_speech_pipeline.jsonl"


def row() -> dict:
    return next(
        json.loads(line)
        for line in DATASET.read_text(encoding="utf-8").splitlines()
        if '"scenarioId": "P5-YUE-004"' in line
    )


def audio(value: dict, payload: bytes | None = None) -> AudioInput:
    return AudioInput(
        payload=payload if payload is not None else (ROOT / value["audioPath"]).read_bytes(),
        content_type=value["contentType"],
        encoding=AudioEncoding(value["encoding"]),
        sample_rate_hz=value["sampleRateHz"],
        channels=value["channels"],
        sample_width_bytes=value["sampleWidthBytes"],
        fixture_id=value["fixtureId"],
        synthetic=True,
    )


def execute(phase5, value: dict):
    return asyncio.run(
        phase5.pipeline.handle_audio_message(
            session_id=f"phase5-independent-{uuid4().hex}",
            restaurant_code=value["restaurantCode"],
            branch_code=value["branchCode"],
            audio=audio(value),
        )
    )


def test_poisoning_expected_fields_does_not_change_provider_or_runtime(phase5):
    original = row()
    poisoned = {
        **original,
        "expectedTranscript": "POISONED EXPECTED TRANSCRIPT",
        "expectedIntent": "POISONED_INTENT",
        "expectedDetectedLocale": "en-HK",
        "expectedClassification": "REFUSE",
    }
    first = execute(phase5, original)
    second = execute(phase5, poisoned)
    assert first.transcript.transcript == second.transcript.transcript
    assert first.transcript.transcript != poisoned["expectedTranscript"]
    assert first.text_result["trace"]["multilingual"]["canonicalIntent"] == "ADD_ITEM"
    assert second.text_result["trace"]["multilingual"]["canonicalIntent"] == "ADD_ITEM"
    assert first.text_result["detected_locale"] == second.text_result["detected_locale"]


def test_auto_locale_does_not_receive_ground_truth_hint(phase5, monkeypatch):
    value = row()
    seen = []
    original = phase5.text_entry.handle_text_message

    async def capture(*args, **kwargs):
        seen.append(kwargs.get("locale_hint"))
        return await original(*args, **kwargs)

    monkeypatch.setattr(phase5.text_entry, "handle_text_message", capture)
    execute(phase5, value)
    assert seen == [None]


def test_replay_provider_never_uses_network(phase5, monkeypatch):
    def blocked(*_args, **_kwargs):
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr(socket, "create_connection", blocked)
    result = execute(phase5, row())
    assert result.transcript.provider_mode.value == "REPLAY"


def test_audio_tampering_fails_independently_of_expected_fields(phase5):
    value = row()
    payload = (ROOT / value["audioPath"]).read_bytes() + b"tampered"
    try:
        asyncio.run(
            phase5.pipeline.handle_audio_message(
                session_id=f"phase5-tamper-{uuid4().hex}",
                restaurant_code=value["restaurantCode"],
                branch_code=value["branchCode"],
                audio=audio(value, payload),
            )
        )
    except Exception as exc:
        assert getattr(exc, "code", None) in {
            "AUDIO_CONTAINER_INVALID",
            "SPEECH_FIXTURE_HASH_MISMATCH",
        }
    else:
        raise AssertionError("tampered fixture was accepted")
