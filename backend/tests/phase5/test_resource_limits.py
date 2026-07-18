from __future__ import annotations

import asyncio
import json
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import pytest

from app.speech.contracts import AudioInput
from app.speech.errors import SpeechError
from app.speech.formats import AudioEncoding


ROOT = Path(__file__).resolve().parents[3]
ROWS = [
    json.loads(line)
    for line in (ROOT / "evaluation" / "phase5_speech_pipeline.jsonl")
    .read_text(encoding="utf-8")
    .splitlines()
]


def row(category: str) -> dict:
    return next(
        item
        for item in ROWS
        if item["locale"] == "zh-CN" and item["semanticCategory"] == category
    )


def audio(item: dict) -> AudioInput:
    return AudioInput(
        payload=(ROOT / item["audioPath"]).read_bytes(),
        content_type=item["contentType"],
        encoding=AudioEncoding(item["encoding"]),
        sample_rate_hz=item["sampleRateHz"],
        channels=item["channels"],
        sample_width_bytes=item["sampleWidthBytes"],
        fixture_id=item["fixtureId"],
        synthetic=True,
    )


async def send(phase5, session_id: str, item: dict):
    return await phase5.pipeline.handle_audio_message(
        session_id=session_id,
        restaurant_code="hk-sim-restaurant-a",
        branch_code="central",
        audio=audio(item),
    )


def test_burst_of_small_fixtures_and_different_sessions_remains_isolated(phase5):
    menu = row("menu")

    async def exercise():
        sessions = [f"phase5-burst-{uuid4().hex}" for _ in range(12)]
        return sessions, await asyncio.gather(*(send(phase5, session, menu) for session in sessions))

    sessions, results = asyncio.run(exercise())
    assert all(result.outcome.value == "SUCCESS" for result in results)
    for session in sessions:
        state = phase5.store.get(session, "hk-sim-restaurant-a", "central")
        assert state.current_order == []


def test_same_session_audio_turns_use_text_entry_lock(phase5):
    add = row("add1")
    session = f"phase5-same-session-{uuid4().hex}"
    phase5.text_entry.ensure_session_context(
        session,
        restaurant_code="hk-sim-restaurant-a",
        branch_code="central",
    )

    async def exercise():
        return await asyncio.gather(send(phase5, session, add), send(phase5, session, add))

    results = asyncio.run(exercise())
    assert all(result.outcome.value == "SUCCESS" for result in results)
    state = phase5.store.get(session, "hk-sim-restaurant-a", "central")
    assert len(state.current_order) == 1
    assert state.current_order[0].quantity == 2


@pytest.mark.parametrize("category", ["too_large", "malformed_wav"])
def test_unsafe_audio_is_rejected_quickly_before_provider(phase5, monkeypatch, category):
    item = row(category)
    provider = phase5.registry.get_asr()
    monkeypatch.setattr(
        provider,
        "transcribe",
        lambda _request: pytest.fail("validator must reject before the Provider"),
    )
    started = perf_counter()
    with pytest.raises(SpeechError) as raised:
        asyncio.run(send(phase5, f"phase5-fast-reject-{uuid4().hex}", item))
    elapsed = perf_counter() - started
    assert raised.value.code == item["expectedErrorCode"]
    assert elapsed < 1.0
