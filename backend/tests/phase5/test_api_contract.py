from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select

import app.api.speech as speech_api
from app.db.models import IdempotencyRecord, Order, OrderConfirmation, SpeechTurnRecord
from app.main import app
from app.speech.config import SpeechSettings
from evaluation.run_phase5_speech_pipeline_eval import temporary_artifact_snapshot


ROOT = Path(__file__).resolve().parents[3]
DATASET = ROOT / "evaluation" / "phase5_speech_pipeline.jsonl"
TTS_MANIFEST = ROOT / "evaluation" / "audio" / "manifests" / "phase5_tts_manifest.jsonl"


def scenario() -> dict:
    return next(
        json.loads(line)
        for line in DATASET.read_text(encoding="utf-8").splitlines()
        if '"scenarioId": "P5-ZH-004"' in line
    )


def scenario_by_category(category: str) -> dict:
    return next(
        row
        for line in DATASET.read_text(encoding="utf-8").splitlines()
        if (row := json.loads(line))["semanticCategory"] == category
        and row["locale"] == "zh-CN"
    )


def headers(row: dict, session_id: str, *, content_type: str | None = None) -> dict[str, str]:
    return {
        "Content-Type": content_type or row["contentType"],
        "X-Fixture-Id": row["fixtureId"],
        "X-Session-Id": session_id,
        "X-Restaurant-Code": row["restaurantCode"],
        "X-Branch-Code": row["branchCode"],
        "X-Audio-Encoding": row["encoding"],
        "X-Sample-Rate-Hz": str(row["sampleRateHz"]),
        "X-Channels": str(row["channels"]),
        "X-Sample-Width-Bytes": str(row["sampleWidthBytes"]),
    }


def enable(phase5, monkeypatch):
    monkeypatch.setattr(speech_api, "speech_settings", phase5.speech_settings)
    monkeypatch.setattr(speech_api, "speech_registry", phase5.registry)
    monkeypatch.setattr(speech_api, "speech_pipeline_service", phase5.pipeline)


def database_row_counts(phase5) -> tuple[int, int, int, int]:
    with phase5.uow_factory() as uow:
        return tuple(
            int(uow.session.scalar(select(func.count(model.id))) or 0)
            for model in (Order, OrderConfirmation, IdempotencyRecord, SpeechTurnRecord)
        )


def test_production_and_default_disabled_are_not_exposed(monkeypatch):
    monkeypatch.setattr(
        speech_api,
        "speech_settings",
        SpeechSettings(app_env="production", simulation_enabled=False),
    )
    response = TestClient(app).get("/api/speech/capabilities")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SPEECH_SIMULATION_DISABLED"


def test_development_transcribe_and_respond_are_explicit_replay(phase5, monkeypatch):
    enable(phase5, monkeypatch)
    client = TestClient(app)
    row = scenario()
    payload = (ROOT / row["audioPath"]).read_bytes()
    session = f"phase5-api-{uuid4().hex}"
    transcribed = client.post("/api/speech/transcribe", content=payload, headers=headers(row, session))
    assert transcribed.status_code == 200
    assert transcribed.json()["transcript"] == row["expectedTranscript"]
    assert transcribed.json()["realSpeechRecognition"] is False
    responded = client.post(
        "/api/speech/respond",
        content=payload,
        headers=headers(row, f"phase5-api-{uuid4().hex}"),
    )
    assert responded.status_code == 200
    body = responded.json()
    assert body["simulation"] is True
    assert body["providerMode"] == "REPLAY"
    assert body["realSpeechRecognition"] is False
    assert body["realSpeechSynthesis"] is False
    assert body["merchantStatus"] == "NOT_INTEGRATED"


def test_fixture_catalog_and_audio_are_synthetic_without_local_paths(phase5, monkeypatch):
    enable(phase5, monkeypatch)
    client = TestClient(app)
    listed = client.get("/api/speech/fixtures")
    assert listed.status_code == 200
    body = listed.json()
    assert body["simulation"] is True
    assert body["realSpeechRecognition"] is False
    assert len(body["fixtures"]) == 236
    assert all("audioPath" not in item for item in body["fixtures"])
    fixture_id = body["fixtures"][0]["fixtureId"]
    audio = client.get(f"/api/speech/fixtures/{fixture_id}/audio")
    assert audio.status_code == 200
    assert audio.content[:4] == b"RIFF"
    assert audio.headers["x-simulation"] == "true"
    missing = client.get("/api/speech/fixtures/not-a-reviewed-fixture/audio")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "SPEECH_FIXTURE_NOT_FOUND"


def test_api_rejects_empty_forged_mime_and_cross_tenant_session(phase5, monkeypatch):
    enable(phase5, monkeypatch)
    client = TestClient(app)
    row = scenario()
    payload = (ROOT / row["audioPath"]).read_bytes()
    session = f"phase5-api-{uuid4().hex}"
    empty = client.post("/api/speech/respond", content=b"", headers=headers(row, session))
    assert empty.status_code == 422
    assert empty.json()["error"]["code"] == "AUDIO_EMPTY"
    forged = client.post(
        "/api/speech/respond",
        content=payload,
        headers=headers(row, session, content_type="audio/mpeg"),
    )
    assert forged.status_code == 422
    assert forged.json()["error"]["code"] == "AUDIO_CONTENT_TYPE_MISMATCH"
    ok = client.post("/api/speech/respond", content=payload, headers=headers(row, session))
    assert ok.status_code == 200
    other = {**row, "restaurantCode": "hk-sim-restaurant-b", "branchCode": "harbor"}
    rejected = client.post("/api/speech/respond", content=payload, headers=headers(other, session))
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "TENANT_CONTEXT_MISMATCH"


def test_cross_tenant_api_rebinding_is_stable_non_leaking_and_read_only(
    phase5, monkeypatch
):
    enable(phase5, monkeypatch)
    client = TestClient(app)
    value = scenario_by_category("confirm")
    payload = (ROOT / value["audioPath"]).read_bytes()
    session_key = f"phase5-api-tenant-a-{uuid4().hex}"
    for setup in value["setupInputs"]:
        asyncio.run(
            phase5.text_entry.handle_text_message(
                session_key,
                setup,
                restaurant_code=value["restaurantCode"],
                branch_code=value["branchCode"],
            )
        )
    created = client.post(
        "/api/speech/respond",
        content=payload,
        headers=headers(value, session_key),
    )
    assert created.status_code == 200
    tenant_a = phase5.tenant_service.resolve(
        value["restaurantCode"], value["branchCode"]
    )
    with phase5.uow_factory() as uow:
        session = uow.sessions.get(
            session_key, tenant_a.restaurant_id, tenant_a.branch_id
        )
        audit = uow.speech.list_scoped(
            session.id, tenant_a.restaurant_id, tenant_a.branch_id
        )[0]
        order = uow.orders.get_latest_for_session(
            session.id, tenant_a.restaurant_id, tenant_a.branch_id
        )
        forbidden_values = {
            session_key,
            value["fixtureId"],
            audit.public_id,
            order.public_id,
        }
    rebound_headers = {
        **headers(value, session_key),
        "X-Restaurant-Code": "hk-sim-restaurant-b",
        "X-Branch-Code": "harbor",
    }
    before = database_row_counts(phase5)
    error_codes = []
    for endpoint in ("respond", "transcribe"):
        observer_snapshot = phase5.invocation_observer.snapshot()
        rejected = client.post(
            f"/api/speech/{endpoint}",
            content=payload,
            headers=rebound_headers,
        )
        assert rejected.status_code == 409
        error_codes.append(rejected.json()["error"]["code"])
        assert not phase5.invocation_observer.events_since(observer_snapshot)
        assert all(value not in rejected.text for value in forbidden_values)
        assert database_row_counts(phase5) == before
    assert error_codes == ["TENANT_CONTEXT_MISMATCH", "TENANT_CONTEXT_MISMATCH"]


def test_audio_upload_request_does_not_create_temporary_files(phase5, monkeypatch):
    enable(phase5, monkeypatch)
    value = scenario()
    before = temporary_artifact_snapshot()
    response = TestClient(app).post(
        "/api/speech/respond",
        content=(ROOT / value["audioPath"]).read_bytes(),
        headers=headers(value, f"phase5-api-memory-only-{uuid4().hex}"),
    )
    after = temporary_artifact_snapshot()
    assert response.status_code == 200
    assert after == before


def test_api_rejects_oversize_malformed_silence_and_hash_mismatch(phase5, monkeypatch):
    enable(phase5, monkeypatch)
    client = TestClient(app)
    for category in ("too_large", "malformed_wav", "silence", "hash_mismatch"):
        row = scenario_by_category(category)
        payload = (ROOT / row["audioPath"]).read_bytes()
        response = client.post(
            "/api/speech/respond",
            content=payload,
            headers=headers(row, f"phase5-api-negative-{category}-{uuid4().hex}"),
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == row["expectedErrorCode"]


def test_api_maps_provider_failures_and_invalid_tenant_without_sensitive_details(phase5, monkeypatch):
    enable(phase5, monkeypatch)
    client = TestClient(app)
    for category, status in (("provider_timeout", 504), ("provider_error", 503)):
        row = scenario_by_category(category)
        payload = (ROOT / row["audioPath"]).read_bytes()
        response = client.post(
            "/api/speech/transcribe",
            content=payload,
            headers=headers(row, f"phase5-api-provider-{category}-{uuid4().hex}"),
        )
        assert response.status_code == status
        error = response.json()["error"]
        assert error["code"] == row["expectedErrorCode"]
        serialized = json.dumps(error)
        assert "DATABASE_URL" not in serialized
        assert "provider_secret" not in serialized
        assert str(ROOT) not in serialized
        assert "Traceback" not in serialized
    row = scenario()
    invalid = {**row, "restaurantCode": "does-not-exist"}
    response = client.post(
        "/api/speech/respond",
        content=(ROOT / row["audioPath"]).read_bytes(),
        headers=headers(invalid, f"phase5-api-invalid-tenant-{uuid4().hex}"),
    )
    assert response.status_code == 404

    unsupported_locale = client.post(
        "/api/speech/transcribe",
        content=(ROOT / row["audioPath"]).read_bytes(),
        headers={
            **headers(row, f"phase5-api-invalid-locale-{uuid4().hex}"),
            "X-Locale-Hint": "fr-FR",
        },
    )
    assert unsupported_locale.status_code == 422
    assert unsupported_locale.json()["error"]["code"] == "SPEECH_LANGUAGE_UNSUPPORTED"


def test_api_does_not_accept_path_or_url_inputs(phase5, monkeypatch):
    enable(phase5, monkeypatch)
    client = TestClient(app)
    row = scenario()
    injected = client.post(
        "/api/speech/respond",
        json={"path": "../../.env", "url": "https://example.invalid/audio.wav"},
        headers=headers(row, f"phase5-api-injection-{uuid4().hex}", content_type="application/json"),
    )
    assert injected.status_code == 422
    assert injected.json()["error"]["code"] == "AUDIO_CONTENT_TYPE_MISMATCH"


def test_tts_endpoint_returns_audio_with_simulation_headers(phase5, monkeypatch):
    enable(phase5, monkeypatch)
    row = json.loads(TTS_MANIFEST.read_text(encoding="utf-8").splitlines()[0])
    response = TestClient(app).post(
        "/api/speech/synthesize",
        headers={
            "X-Session-Id": f"phase5-tts-api-{uuid4().hex}",
            "X-Restaurant-Code": "hk-sim-restaurant-a",
            "X-Branch-Code": "central",
        },
        json={
            "text": row["text"],
            "locale": row["locale"],
            "voiceId": row["voiceId"],
            "sampleRateHz": row["sampleRateHz"],
            "outputEncoding": row["encoding"],
        },
    )
    assert response.status_code == 200
    assert response.content[:4] == b"RIFF"
    assert response.headers["x-simulation"] == "true"
    assert response.headers["x-provider-mode"] == "REPLAY"
    assert response.headers["x-real-speech-synthesis"] == "false"


def test_tts_rejects_invalid_locale_missing_fixture_and_extra_path_fields(phase5, monkeypatch):
    enable(phase5, monkeypatch)
    client = TestClient(app)
    request_headers = {
        "X-Session-Id": f"phase5-tts-negative-{uuid4().hex}",
        "X-Restaurant-Code": "hk-sim-restaurant-a",
        "X-Branch-Code": "central",
    }
    invalid_locale = client.post(
        "/api/speech/synthesize",
        headers=request_headers,
        json={"text": "synthetic only", "locale": "fr-FR"},
    )
    assert invalid_locale.status_code == 422
    assert invalid_locale.json()["error"]["code"] == "SPEECH_LANGUAGE_UNSUPPORTED"
    missing = client.post(
        "/api/speech/synthesize",
        headers=request_headers,
        json={"text": "not in the reviewed manifest", "locale": "en-HK"},
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "TTS_FIXTURE_NOT_FOUND"
    forbidden_extra = client.post(
        "/api/speech/synthesize",
        headers=request_headers,
        json={"text": "synthetic only", "locale": "en-HK", "path": "../../.env"},
    )
    assert forbidden_extra.status_code == 422
