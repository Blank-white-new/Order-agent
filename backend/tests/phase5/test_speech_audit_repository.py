from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import LargeBinary, inspect

from app.db.base import Base
from app.speech.config import SpeechSettings
from app.speech.contracts import AudioInput
from app.speech.formats import AudioEncoding


ROOT = Path(__file__).resolve().parents[3]
FORBIDDEN_COLUMNS = {
    "raw_audio",
    "audio_payload",
    "audio_blob",
    "full_transcript",
    "transcript_text",
    "full_address",
    "full_phone",
    "provider_secret",
    "voiceprint",
    "speaker_embedding",
}


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
        values = [getattr(record, column.name) for column in record.__table__.columns]
        assert payload not in values
        assert base64.b64encode(payload).decode("ascii") not in values
        assert not any(isinstance(value, (bytes, bytearray, memoryview)) for value in values)
    columns = {column["name"] for column in inspect(phase5.database.engine).get_columns("speech_turn_records")}
    metadata_columns = {
        column.name for column in Base.metadata.tables["speech_turn_records"].columns
    }
    assert FORBIDDEN_COLUMNS.isdisjoint(columns)
    assert FORBIDDEN_COLUMNS.isdisjoint(metadata_columns)
    assert not any(
        isinstance(column.type, LargeBinary)
        for column in Base.metadata.tables["speech_turn_records"].columns
    )
    assert all(
        "BLOB" not in str(column["type"]).upper()
        and "BINARY" not in str(column["type"]).upper()
        and "BYTEA" not in str(column["type"]).upper()
        for column in inspect(phase5.database.engine).get_columns("speech_turn_records")
    )


def test_audio_retention_configuration_cannot_be_enabled(monkeypatch):
    monkeypatch.setenv("SPEECH_AUDIO_RETENTION_ENABLED", "false")
    assert SpeechSettings.from_env(app_env="test").audio_retention_enabled is False
    monkeypatch.setenv("SPEECH_AUDIO_RETENTION_ENABLED", "true")
    with pytest.raises(ValueError, match="does not permit persistent audio retention"):
        SpeechSettings.from_env(app_env="test")
