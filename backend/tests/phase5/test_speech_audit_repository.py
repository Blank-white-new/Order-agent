from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import uuid4

from sqlalchemy import inspect

from app.speech.contracts import AudioInput
from app.speech.formats import AudioEncoding


ROOT = Path(__file__).resolve().parents[3]


def test_speech_audit_persists_allow_list_without_audio_or_transcript(phase5):
    row = next(
        json.loads(line)
        for line in (ROOT / "evaluation" / "phase5_speech_pipeline.jsonl").read_text(encoding="utf-8").splitlines()
        if '"scenarioId": "P5-ZH-001"' in line
    )
    session_key = f"phase5-audit-{uuid4().hex}"
    payload = (ROOT / row["audioPath"]).read_bytes()
    asyncio.run(
        phase5.pipeline.handle_audio_message(
            session_id=session_key,
            restaurant_code="hk-sim-restaurant-a",
            branch_code="central",
            audio=AudioInput(
                payload=payload,
                content_type="audio/wav",
                encoding=AudioEncoding.WAV_PCM_S16LE,
                sample_rate_hz=16000,
                channels=1,
                sample_width_bytes=2,
                fixture_id=row["fixtureId"],
                synthetic=True,
            ),
        )
    )
    tenant = phase5.tenant_service.resolve("hk-sim-restaurant-a", "central")
    with phase5.uow_factory() as uow:
        session = uow.sessions.get(session_key, tenant.restaurant_id, tenant.branch_id)
        records = uow.speech.list_scoped(session.id, tenant.restaurant_id, tenant.branch_id)
        assert len(records) == 1
        record = records[0]
        assert record.audio_sha256
        assert record.fixture_id == row["fixtureId"]
        assert record.provider_mode == "REPLAY"
        assert record.is_synthetic is True
    columns = {column["name"] for column in inspect(phase5.database.engine).get_columns("speech_turn_records")}
    assert "raw_audio" not in columns
    assert "full_transcript" not in columns
    assert "full_address" not in columns
    assert "full_phone" not in columns
    assert "provider_secret" not in columns
