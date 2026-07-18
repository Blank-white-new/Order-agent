from __future__ import annotations

import asyncio
import http.client
import json
import socket
import tempfile
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import inspect

from app.speech.contracts import AudioInput
from app.speech.formats import AudioEncoding, ProviderMode
from app.speech.invocation_observer import ProviderInvocation, ProviderInvocationObserver
from evaluation.run_phase5_speech_pipeline_eval import (
    Metric,
    NetworkInvocationGuard,
    apply_audit_schema_metrics,
    apply_temporary_artifact_metrics,
    audit_record_excludes_raw_audio,
    new_metrics,
    record_logging_metrics,
    record_provider_metrics,
    temporary_artifact_snapshot,
)


ROOT = Path(__file__).resolve().parents[3]
DATASET = ROOT / "evaluation" / "phase5_speech_pipeline.jsonl"


def row() -> dict:
    return next(
        json.loads(line)
        for line in DATASET.read_text(encoding="utf-8").splitlines()
        if '"scenarioId": "P5-YUE-004"' in line
    )


def row_by_category(category: str) -> dict:
    return next(
        value
        for line in DATASET.read_text(encoding="utf-8").splitlines()
        if (value := json.loads(line))["semanticCategory"] == category
        and value["locale"] == "zh-CN"
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


def execute_observed(phase5, value: dict):
    snapshot = phase5.invocation_observer.snapshot()
    try:
        result = execute(phase5, value)
    except Exception as exc:
        result = None
        error = exc
    else:
        error = None
    events = phase5.invocation_observer.events_since(snapshot)
    return result, error, events


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


@pytest.mark.parametrize(
    ("category", "expected_lookup", "expected_hash", "expected_metadata"),
    [
        ("too_short", 0, 0, 0),
        ("fixture_not_found", 1, 0, 0),
        ("hash_mismatch", 1, 1, 0),
        ("menu", 1, 1, 1),
    ],
)
def test_provider_stage_denominators_follow_actual_execution(
    phase5,
    category,
    expected_lookup,
    expected_hash,
    expected_metadata,
):
    value = row_by_category(category)
    _result, _error, events = execute_observed(phase5, value)
    try:
        phase5.validator.validate(audio(value))
    except Exception:
        validation_failed = True
    else:
        validation_failed = False
    metrics = new_metrics()
    record_provider_metrics(
        metrics,
        events[0] if events else None,
        validation_failed=validation_failed,
        expected_error_code=value["expectedErrorCode"],
    )
    assert metrics["fixture_lookup"].checks == expected_lookup
    assert metrics["fixture_hash"].checks == expected_hash
    assert metrics["fixture_metadata"].checks == expected_metadata
    assert metrics["provider_not_invoked_validation_failure"].checks == int(
        validation_failed
    )
    assert all(metric.checks == metric.matches for metric in metrics.values())


@pytest.mark.parametrize("category", ["provider_timeout", "provider_error"])
def test_replay_failure_still_records_real_invocation(phase5, category):
    value = row_by_category(category)
    _result, error, events = execute_observed(phase5, value)
    assert error is None
    assert len(events) == 1
    assert events[0].provider_mode == ProviderMode.REPLAY
    assert events[0].success is False
    assert events[0].error_code == value["expectedErrorCode"]


def test_audio_validator_failure_has_zero_provider_invocations(phase5):
    value = row_by_category("too_short")
    _result, error, events = execute_observed(phase5, value)
    assert getattr(error, "code", None) == value["expectedErrorCode"]
    assert events == ()


def test_transcript_log_denominator_uses_actual_transcript():
    metrics = new_metrics()
    result = SimpleNamespace(
        transcript=SimpleNamespace(transcript="actual synthetic transcript")
    )
    record_logging_metrics(
        metrics,
        row={"expectedTranscript": None},
        result=result,
        scenario_log="safe summary only",
        manifest_transcript="manifest text is irrelevant",
    )
    assert metrics["full_transcript_log"].checks == 1
    assert metrics["no_transcript_failure_log"].checks == 0


def test_poisoned_expected_transcript_does_not_change_log_scan_object():
    metrics = new_metrics()
    result = SimpleNamespace(transcript=SimpleNamespace(transcript="actual transcript"))
    record_logging_metrics(
        metrics,
        row={"expectedTranscript": "POISONED EXPECTED TRANSCRIPT"},
        result=result,
        scenario_log="POISONED EXPECTED TRANSCRIPT",
        manifest_transcript="manifest transcript",
    )
    assert metrics["full_transcript_log"].matches == 1


def test_audit_record_existence_is_separate_from_raw_audio_retention(phase5):
    value = row_by_category("menu")
    session_key = f"phase5-audit-independent-{uuid4().hex}"
    input_audio = audio(value)
    asyncio.run(
        phase5.pipeline.handle_audio_message(
            session_id=session_key,
            restaurant_code=value["restaurantCode"],
            branch_code=value["branchCode"],
            audio=input_audio,
        )
    )
    tenant = phase5.tenant_service.resolve(
        value["restaurantCode"], value["branchCode"]
    )
    with phase5.uow_factory() as uow:
        session = uow.sessions.get(
            session_key, tenant.restaurant_id, tenant.branch_id
        )
        records = uow.speech.list_scoped(
            session.id, tenant.restaurant_id, tenant.branch_id
        )
    assert len(records) == 1
    assert audit_record_excludes_raw_audio(records[0], input_audio)
    assert not any(
        isinstance(getattr(records[0], column.name), (bytes, bytearray, memoryview))
        for column in records[0].__table__.columns
    )


def test_forbidden_audit_columns_use_metadata_and_database_schema(phase5):
    metrics = new_metrics()
    apply_audit_schema_metrics(metrics, phase5.database.engine)
    assert metrics["audit_schema"].checks == 20
    assert metrics["audit_schema"].matches == 20
    columns = {
        column["name"]
        for column in inspect(phase5.database.engine).get_columns("speech_turn_records")
    }
    assert "raw_audio" not in columns
    assert "full_transcript" not in columns


def test_phase5_evaluator_temporary_directory_is_cleaned():
    before = temporary_artifact_snapshot()
    temporary = tempfile.TemporaryDirectory(prefix="phase5-speech-eval-")
    Path(temporary.name, "synthetic.pcm").write_bytes(b"synthetic")
    temporary.cleanup()
    metrics = new_metrics()
    leaks = apply_temporary_artifact_metrics(
        metrics, before, temporary_artifact_snapshot()
    )
    assert leaks == 0
    assert metrics["temporary_audio_file"].checks == 3
    assert metrics["temporary_audio_file"].matches == 3


def test_cross_tenant_classification_and_real_access_metrics_are_distinct():
    metrics = new_metrics()
    metrics["cross_tenant_refusal_classification"].add(True)
    assert metrics["cross_tenant_refusal_classification"].checks == 1
    assert metrics["cross_tenant_session_access"].checks == 0
    assert metrics["cross_tenant_speech_record_write"].checks == 0


def test_zero_denominator_serializes_as_not_evaluated():
    assert Metric().serializable() == {
        "checks": 0,
        "matches": 0,
        "rate": "not_evaluated",
    }


def test_live_provider_count_comes_from_invocation_observer():
    observer = ProviderInvocationObserver()
    observer.record(
        ProviderInvocation(
            provider_name="synthetic-live-spy",
            provider_mode=ProviderMode.LIVE,
            requires_network=True,
            operation="transcribe",
        )
    )
    observer.record(
        ProviderInvocation(
            provider_name="replay",
            provider_mode=ProviderMode.REPLAY,
            requires_network=False,
            operation="transcribe",
        )
    )
    assert sum(event.provider_mode == ProviderMode.LIVE for event in observer.events) == 1


@pytest.mark.parametrize(
    "entry_point",
    [
        "socket.create_connection",
        "socket.socket.connect",
        "urllib.request.urlopen",
        "http.client.HTTPConnection.connect",
    ],
)
def test_network_count_comes_from_patched_entry_points(
    phase5, monkeypatch, entry_point
):
    provider = phase5.registry.get_asr()
    original = provider._transcribe

    def attempted_network(request, invocation):
        if entry_point == "socket.create_connection":
            socket.create_connection(("127.0.0.1", 9))
        elif entry_point == "socket.socket.connect":
            socket.socket().connect(("127.0.0.1", 9))
        elif entry_point == "urllib.request.urlopen":
            urllib.request.urlopen("http://127.0.0.1:9")
        else:
            http.client.HTTPConnection("127.0.0.1", 9).connect()
        return original(request, invocation)

    monkeypatch.setattr(provider, "_transcribe", attempted_network)
    guard = NetworkInvocationGuard()
    with guard:
        result, error, _events = execute_observed(phase5, row())
    assert error is None
    assert result.error_code == "SPEECH_PROVIDER_FAILURE"
    assert guard.total == 1
    assert guard.counts[entry_point] == 1


def test_expected_fields_never_enter_provider_parser_or_text_entry(phase5, monkeypatch):
    value = {
        **row(),
        "expectedTranscript": "POISONED_EXPECTED_TRANSCRIPT_QZ",
        "expectedIntent": "POISONED_EXPECTED_INTENT_QZ",
    }
    provider = phase5.registry.get_asr()
    original_provider = provider._transcribe
    original_text = phase5.text_entry.handle_text_message
    seen_provider_requests = []
    seen_text_inputs = []

    def capture_provider(request, invocation):
        seen_provider_requests.append(request)
        return original_provider(request, invocation)

    async def capture_text(session_id, text, **kwargs):
        seen_text_inputs.append(text)
        return await original_text(session_id, text, **kwargs)

    monkeypatch.setattr(provider, "_transcribe", capture_provider)
    monkeypatch.setattr(phase5.text_entry, "handle_text_message", capture_text)
    result = execute(phase5, value)
    assert len(seen_provider_requests) == 1
    assert seen_text_inputs == [result.transcript.transcript]
    assert value["expectedTranscript"] not in seen_text_inputs
    assert value["expectedIntent"] not in json.dumps(
        result.text_result["trace"], ensure_ascii=False, default=str
    )
