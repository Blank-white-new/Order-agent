from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import http.client
import inspect as python_inspect
import io
import json
import logging
import math
import os
import re
import socket
import sys
import tempfile
import time
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import LargeBinary, func, inspect, select
from sqlalchemy.exc import IntegrityError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.phase5_harness import ROOT, make_phase5_context

from app.db.base import Base
from app.db.models import IdempotencyRecord, Order, OrderConfirmation, SpeechTurnRecord
from app.speech.config import SpeechSettings
from app.speech.contracts import AudioInput
from app.speech.errors import SpeechError
from app.speech.formats import AudioEncoding, ProviderMode, SpeechOutcome
from app.speech.invocation_observer import ProviderInvocation


DATASET = ROOT / "evaluation" / "phase5_speech_pipeline.jsonl"
ASR_MANIFEST = ROOT / "evaluation" / "audio" / "manifests" / "phase5_asr_manifest.jsonl"
VALIDATION_CODES = {
    "AUDIO_TOO_LARGE",
    "AUDIO_TOO_SHORT",
    "AUDIO_TOO_LONG",
    "AUDIO_CHANNELS_UNSUPPORTED",
    "AUDIO_SAMPLE_RATE_UNSUPPORTED",
    "AUDIO_SAMPLE_WIDTH_UNSUPPORTED",
    "AUDIO_ENCODING_UNSUPPORTED",
    "AUDIO_CONTAINER_INVALID",
    "AUDIO_TRUNCATED",
    "AUDIO_EMPTY",
    "AUDIO_SILENT",
    "AUDIO_CONTENT_TYPE_MISMATCH",
}
PROVIDER_FAILURE_CODES = {
    "AUDIO_TRUNCATED",
    "NO_SPEECH_DETECTED",
    "SPEECH_FIXTURE_HASH_MISMATCH",
    "SPEECH_FIXTURE_NOT_FOUND",
    "SPEECH_LANGUAGE_UNSUPPORTED",
    "SPEECH_PROVIDER_FAILURE",
    "SPEECH_TIMEOUT",
}
FORBIDDEN_AUDIT_COLUMNS = {
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
AUDIT_ALLOWED_COLUMNS = {column.name for column in SpeechTurnRecord.__table__.columns}
METRIC_NAMES = (
    "audio_validation",
    "fixture_lookup",
    "fixture_hash",
    "fixture_metadata",
    "fixture_not_found",
    "provider_not_invoked_validation_failure",
    "transcript",
    "locale",
    "intent",
    "classification",
    "item",
    "quantity",
    "mutation",
    "handoff_reason",
    "refusal_reason",
    "no_speech",
    "low_confidence",
    "provider_failure",
    "provider_invocation",
    "replay_provider_invocation",
    "provider_not_invoked",
    "provider_failure_invocation",
    "replay_provider_network_entry_point",
    "database_order",
    "database_confirmation",
    "database_idempotency",
    "cross_tenant_refusal_classification",
    "cross_tenant_session_access",
    "cross_tenant_order_reference",
    "cross_tenant_speech_record_write",
    "wrong_tenant_repository_read",
    "cross_tenant_api_rebinding",
    "production_simulation_endpoint",
    "speech_audit_record",
    "audit_schema",
    "raw_audio_database",
    "temporary_audio_file",
    "audio_retention_configuration",
    "full_transcript_log",
    "no_transcript_candidate_log",
    "fixture_not_found_log_structure",
    "sensitive_field_log",
    "live_llm",
)
NETWORK_ENTRY_POINTS = (
    "socket.create_connection",
    "socket.socket.connect",
    "urllib.request.urlopen",
    "http.client.HTTPConnection.connect",
)


@dataclass
class Metric:
    checks: int = 0
    matches: int = 0

    def add(self, matched: bool) -> None:
        self.checks += 1
        self.matches += int(bool(matched))

    def serializable(self) -> dict:
        return {
            "checks": self.checks,
            "matches": self.matches,
            "rate": "not_evaluated" if self.checks == 0 else self.matches / self.checks,
        }


class ReplayProviderNetworkInvocationGuard:
    """Block and count controlled network entries reached from Replay Providers only."""

    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()
        self._originals: dict[str, object] = {}

    def _blocked(self, name: str, original):
        def blocked(*args, **kwargs):
            provider_origin = any(
                frame.filename.endswith(("replay_asr_provider.py", "replay_tts_provider.py"))
                for frame in python_inspect.stack()
            )
            if provider_origin:
                self.counts[name] += 1
                raise AssertionError(
                    f"Replay Provider-origin network invocation is forbidden: {name}"
                )
            return original(*args, **kwargs)

        return blocked

    def __enter__(self) -> "ReplayProviderNetworkInvocationGuard":
        self._originals = {
            "socket.create_connection": socket.create_connection,
            "socket.socket.connect": socket.socket.connect,
            "urllib.request.urlopen": urllib.request.urlopen,
            "http.client.HTTPConnection.connect": http.client.HTTPConnection.connect,
        }
        socket.create_connection = self._blocked(
            "socket.create_connection", self._originals["socket.create_connection"]
        )
        socket.socket.connect = self._blocked(
            "socket.socket.connect", self._originals["socket.socket.connect"]
        )
        urllib.request.urlopen = self._blocked(
            "urllib.request.urlopen", self._originals["urllib.request.urlopen"]
        )
        http.client.HTTPConnection.connect = self._blocked(
            "http.client.HTTPConnection.connect",
            self._originals["http.client.HTTPConnection.connect"],
        )
        return self

    def __exit__(self, *_exc_info) -> None:
        socket.create_connection = self._originals["socket.create_connection"]
        socket.socket.connect = self._originals["socket.socket.connect"]
        urllib.request.urlopen = self._originals["urllib.request.urlopen"]
        http.client.HTTPConnection.connect = self._originals[
            "http.client.HTTPConnection.connect"
        ]

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def replay_provider_network_result_fields(
    guard: ReplayProviderNetworkInvocationGuard,
) -> dict[str, int]:
    """Return narrowly scoped, user-visible Replay Provider network evidence."""

    return {"replay_provider_origin_network_invocations": guard.total}


def new_metrics() -> dict[str, Metric]:
    return {name: Metric() for name in METRIC_NAMES}


def load_rows() -> list[dict]:
    return [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines()]


def load_manifest_transcripts() -> dict[str, str]:
    return {
        row["fixtureId"]: str(row.get("transcript") or "")
        for line in ASR_MANIFEST.read_text(encoding="utf-8").splitlines()
        if (row := json.loads(line)).get("fixtureId")
    }


def load_manifest_fixture_ids() -> set[str]:
    return {
        str(row["fixtureId"])
        for line in ASR_MANIFEST.read_text(encoding="utf-8").splitlines()
        if (row := json.loads(line)).get("fixtureId")
    }


def audio_input(row: dict) -> AudioInput:
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


def business_fingerprint(state: dict) -> str:
    keys = (
        "current_order",
        "fulfillment_type",
        "official_delivery_address",
        "pending_delivery_address_candidate",
        "phone",
        "lifecycle_status",
        "merchant_status",
        "submitted",
        "submitted_order_id",
    )
    return json.dumps({key: state.get(key) for key in keys}, ensure_ascii=False, sort_keys=True)


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1)
    return round(ordered[index], 3)


def latency(values: list[float]) -> dict:
    return {
        "count": len(values),
        "p50Ms": percentile(values, 0.50),
        "p95Ms": percentile(values, 0.95),
        "maxMs": round(max(values, default=0.0), 3),
    }


def database_counts(context, session_key: str, tenant_codes: tuple[str, str]) -> tuple[int, int, int]:
    tenant = context.tenant_service.resolve(*tenant_codes)
    with context.uow_factory() as uow:
        session = uow.sessions.get(session_key, tenant.restaurant_id, tenant.branch_id)
        if session is None:
            return 0, 0, 0
        scope = (
            Order.session_id == session.id,
            Order.restaurant_id == tenant.restaurant_id,
            Order.branch_id == tenant.branch_id,
        )
        order_count = int(uow.session.scalar(select(func.count(Order.id)).where(*scope)) or 0)
        confirmation_count = int(
            uow.session.scalar(
                select(func.count(OrderConfirmation.id))
                .join(Order, OrderConfirmation.order_id == Order.id)
                .where(*scope, OrderConfirmation.invalidated_at.is_(None))
            )
            or 0
        )
        idempotency_count = int(
            uow.session.scalar(
                select(func.count(IdempotencyRecord.id))
                .join(Order, IdempotencyRecord.resource_id == Order.public_id)
                .where(
                    *scope,
                    IdempotencyRecord.restaurant_id == tenant.restaurant_id,
                    IdempotencyRecord.branch_id == tenant.branch_id,
                    IdempotencyRecord.scope == "ORDER_CONFIRMATION",
                )
            )
            or 0
        )
        return order_count, confirmation_count, idempotency_count


def speech_audit_records(context, session_key: str, tenant_codes: tuple[str, str]) -> list[SpeechTurnRecord]:
    tenant = context.tenant_service.resolve(*tenant_codes)
    with context.uow_factory() as uow:
        session = uow.sessions.get(session_key, tenant.restaurant_id, tenant.branch_id)
        if session is None:
            return []
        return uow.speech.list_scoped(session.id, tenant.restaurant_id, tenant.branch_id)


def audit_record_excludes_raw_audio(record: SpeechTurnRecord, audio: AudioInput) -> bool:
    encoded_payload = base64.b64encode(audio.payload).decode("ascii")
    values = [getattr(record, column.name) for column in SpeechTurnRecord.__table__.columns]
    has_binary_value = any(isinstance(value, (bytes, bytearray, memoryview)) for value in values)
    has_full_base64 = any(
        isinstance(value, str) and value == encoded_payload for value in values
    )
    return (
        not has_binary_value
        and not has_full_base64
        and record.audio_sha256 == hashlib.sha256(audio.payload).hexdigest()
        and {column.name for column in record.__table__.columns} == AUDIT_ALLOWED_COLUMNS
    )


def record_provider_metrics(
    metrics: dict[str, Metric],
    invocation: ProviderInvocation | None,
    *,
    validation_failed: bool,
    expected_error_code: str | None,
) -> None:
    should_invoke = not validation_failed
    metrics["provider_invocation"].add((invocation is not None) == should_invoke)
    if not should_invoke:
        metrics["provider_not_invoked"].add(invocation is None)
        metrics["provider_not_invoked_validation_failure"].add(invocation is None)
        return
    if invocation is None:
        return

    metrics["replay_provider_invocation"].add(
        invocation.provider_name == "replay"
        and invocation.provider_mode == ProviderMode.REPLAY
        and invocation.requires_network is False
        and invocation.operation == "transcribe"
    )
    if invocation.fixture_lookup_performed:
        expected_found = expected_error_code != "SPEECH_FIXTURE_NOT_FOUND"
        metrics["fixture_lookup"].add(invocation.fixture_found is expected_found)
    if expected_error_code == "SPEECH_FIXTURE_NOT_FOUND":
        metrics["fixture_not_found"].add(
            invocation.fixture_lookup_performed
            and invocation.fixture_found is False
            and invocation.error_code == "SPEECH_FIXTURE_NOT_FOUND"
        )
    if invocation.hash_comparison_performed:
        expected_hash_match = expected_error_code != "SPEECH_FIXTURE_HASH_MISMATCH"
        metrics["fixture_hash"].add(invocation.hash_matched is expected_hash_match)
    if invocation.metadata_comparison_performed:
        metrics["fixture_metadata"].add(invocation.metadata_matched is True)
    if expected_error_code in PROVIDER_FAILURE_CODES:
        metrics["provider_failure_invocation"].add(
            not invocation.success and invocation.error_code == expected_error_code
        )


def record_logging_metrics(
    metrics: dict[str, Metric],
    *,
    row: dict,
    result,
    scenario_log: str,
    scenario_trace: dict | None,
    manifest_transcript: str | None,
    all_manifest_transcripts: set[str],
    all_manifest_fixture_ids: set[str],
    audio: AudioInput | None = None,
    actual_error_code: str | None = None,
    actual_mutation: bool | None = None,
    database_record_counts: tuple[int, int, int] | None = None,
    audit_record_safe: bool | None = None,
) -> None:
    transcript_envelope_absent = result is None or result.transcript is None
    actual_transcript = (
        result.transcript.transcript
        if not transcript_envelope_absent
        else None
    )
    if actual_transcript:
        metrics["full_transcript_log"].add(actual_transcript not in scenario_log)
        return
    candidates = {
        value
        for value in (row.get("expectedTranscript"), manifest_transcript)
        if isinstance(value, str) and value
    }
    if candidates:
        metrics["no_transcript_candidate_log"].add(
            all(candidate not in scenario_log for candidate in candidates)
        )
        return

    if not (
        row.get("semanticCategory") == "fixture_not_found"
        or actual_error_code == "SPEECH_FIXTURE_NOT_FOUND"
    ):
        return

    serialized_trace = json.dumps(
        scenario_trace or {}, ensure_ascii=False, sort_keys=True, default=str
    )
    observable = f"{scenario_log}\n{serialized_trace}"
    folded_observable = observable.casefold()
    current_fixture_id = str(row.get("fixtureId") or "")
    other_fixture_ids = all_manifest_fixture_ids - {current_fixture_id}
    forbidden_tokens = {
        "transcriptenvelope",
        '"transcript"',
        "'transcript'",
        "transcript=",
        "full_transcript",
        "transcript_text",
        "audio_payload",
        "audio_blob",
        "raw_audio",
        '"fixtureid"',
        '"audiopath"',
    }
    forbidden_paths = {
        str(PROJECT_ROOT),
        PROJECT_ROOT.as_posix(),
        str(ASR_MANIFEST),
        ASR_MANIFEST.as_posix(),
        ASR_MANIFEST.name,
    }
    encoded_audio = (
        base64.b64encode(audio.payload).decode("ascii") if audio is not None else ""
    )
    absolute_path_leaked = re.search(
        r'(?:[A-Za-z]:[\\/]|(?:^|["\s])/(?:[^/\s"]+/)+)', observable
    )
    log_words = {word.casefold() for word in re.findall(r"[A-Za-z_]+", scenario_log)}
    allowed_log_words = {
        "speech_fixture_not_found",
        "provider",
        "provider_mode",
        "replay",
        "outcome",
        "validation_error",
        "reason_code",
        "direction",
        "input",
        "synthetic",
        "true",
    }
    structure_safe = (
        transcript_envelope_absent
        and actual_error_code == "SPEECH_FIXTURE_NOT_FOUND"
        and not any(token in folded_observable for token in forbidden_tokens)
        and not any(
            path and path.casefold() in folded_observable for path in forbidden_paths
        )
        and not any(
            transcript and transcript in observable
            for transcript in all_manifest_transcripts
        )
        and not any(
            fixture_id and fixture_id in observable for fixture_id in other_fixture_ids
        )
        and (not encoded_audio or encoded_audio not in observable)
        and absolute_path_leaked is None
        and log_words <= allowed_log_words
        and actual_mutation is False
        and database_record_counts == (0, 0, 0)
        and audit_record_safe is True
    )
    metrics["fixture_not_found_log_structure"].add(structure_safe)


def apply_audit_schema_metrics(metrics: dict[str, Metric], engine) -> None:
    metadata_columns = {column.name.casefold() for column in Base.metadata.tables["speech_turn_records"].columns}
    database_columns = {
        column["name"].casefold()
        for column in inspect(engine).get_columns("speech_turn_records")
    }
    for forbidden in sorted(FORBIDDEN_AUDIT_COLUMNS):
        metrics["audit_schema"].add(forbidden not in metadata_columns)
        metrics["audit_schema"].add(forbidden not in database_columns)
    binary_free = all(
        not isinstance(column.type, LargeBinary)
        for column in Base.metadata.tables["speech_turn_records"].columns
    ) and all(
        "BLOB" not in str(column["type"]).upper()
        and "BINARY" not in str(column["type"]).upper()
        and "BYTEA" not in str(column["type"]).upper()
        for column in inspect(engine).get_columns("speech_turn_records")
    )
    metrics["raw_audio_database"].add(binary_free)


def apply_retention_configuration_metrics(metrics: dict[str, Metric], settings: SpeechSettings) -> None:
    metrics["audio_retention_configuration"].add(settings.audio_retention_enabled is False)
    try:
        SpeechSettings(audio_retention_enabled=True)
    except ValueError:
        rejected = True
    else:
        rejected = False
    metrics["audio_retention_configuration"].add(rejected)


def temporary_artifact_snapshot() -> dict[str, set[str]]:
    ignored = {".git", ".venv", ".tooling-venv", "node_modules", "dist", "__pycache__"}
    repository_files = {"wav": set(), "pcm": set(), "tmp": set()}
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in ignored for part in path.parts):
            continue
        suffix = path.suffix.casefold().lstrip(".")
        if suffix in repository_files:
            repository_files[suffix].add(str(path.resolve()))
    evaluation_temp = {
        str(path.resolve())
        for path in Path(tempfile.gettempdir()).glob("phase5-speech-eval-*")
    }
    return {"evaluation_temp": evaluation_temp, **repository_files}


def apply_temporary_artifact_metrics(
    metrics: dict[str, Metric],
    before: dict[str, set[str]],
    after: dict[str, set[str]],
) -> int:
    leaks = {
        name: after[name] - before[name]
        for name in ("evaluation_temp", "wav", "pcm", "tmp")
    }
    metrics["temporary_audio_file"].add(not leaks["evaluation_temp"])
    metrics["temporary_audio_file"].add(not leaks["wav"] and not leaks["pcm"])
    metrics["temporary_audio_file"].add(not leaks["tmp"])
    return sum(len(paths) for paths in leaks.values())


def _negative_record(**changes) -> SpeechTurnRecord:
    values = {
        "public_id": f"SIM-ST-{uuid4().hex[:20].upper()}",
        "restaurant_id": 1,
        "branch_id": 1,
        "session_id": 1,
        "order_id": None,
        "direction": "INPUT",
        "provider_name": "replay",
        "provider_mode": "REPLAY",
        "audio_encoding": "WAV_PCM_S16LE",
        "sample_rate_hz": 16_000,
        "duration_ms": 250,
        "audio_sha256": "a" * 64,
        "fixture_id": "synthetic-tenant-negative",
        "detected_locale": "zh-CN",
        "response_locale": "zh-CN",
        "confidence_bucket": "HIGH",
        "decision_classification": "REFUSE",
        "reason_code": "CROSS_TENANT_ACCESS",
        "outcome": "SUCCESS",
        "trace_id": "SIM-TENANT-NEGATIVE",
        "is_synthetic": True,
        "created_at": datetime.now(timezone.utc),
    }
    values.update(changes)
    return SpeechTurnRecord(**values)


def _safe_table_counts(context) -> tuple[int, int, int, int, int]:
    with context.uow_factory() as uow:
        return (
            int(uow.session.scalar(select(func.count(Order.id))) or 0),
            int(uow.session.scalar(select(func.count(OrderConfirmation.id))) or 0),
            int(uow.session.scalar(select(func.count(IdempotencyRecord.id))) or 0),
            int(uow.session.scalar(select(func.count(SpeechTurnRecord.id))) or 0),
            int(
                uow.session.scalar(
                    select(func.count()).select_from(Base.metadata.tables["conversation_sessions"])
                )
                or 0
            ),
        )


def evaluate_tenant_isolation(
    context,
    metrics: dict[str, Metric],
    *,
    target: dict,
    order_target: dict,
) -> int:
    tenant_a = context.tenant_service.resolve(*target["tenant_codes"])
    tenant_b = context.tenant_service.resolve("hk-sim-restaurant-b", "harbor")
    leaks = 0
    with context.uow_factory() as uow:
        session_a = uow.sessions.get(
            target["session_key"], tenant_a.restaurant_id, tenant_a.branch_id
        )
        audit_a = uow.speech.list_scoped(
            session_a.id, tenant_a.restaurant_id, tenant_a.branch_id
        )[0]
        order_a = uow.orders.get_latest_for_session(
            order_target["session_db_id"], tenant_a.restaurant_id, tenant_a.branch_id
        )
        target_ids = {
            target["session_key"],
            audit_a.public_id,
            target["row"]["fixtureId"],
            order_a.public_id,
        }

    before = _safe_table_counts(context)
    observer_snapshot = context.invocation_observer.snapshot()
    try:
        asyncio.run(
            context.pipeline.handle_audio_message(
                session_id=target["session_key"],
                restaurant_code="hk-sim-restaurant-b",
                branch_code="harbor",
                audio=audio_input(target["row"]),
            )
        )
    except Exception as exc:
        session_rejected = getattr(exc, "code", None) == "TENANT_CONTEXT_MISMATCH"
        detail = str(exc)
    else:
        session_rejected = False
        detail = ""
    no_provider_call = not context.invocation_observer.events_since(observer_snapshot)
    unchanged = before == _safe_table_counts(context)
    no_detail_leak = all(identifier not in detail for identifier in target_ids)
    metrics["cross_tenant_session_access"].add(
        session_rejected and no_provider_call and unchanged and no_detail_leak
    )
    leaks += int(not unchanged or not no_detail_leak)

    repository_results = []
    with context.uow_factory() as uow:
        repository_results.append(
            uow.speech.get_scoped(audit_a.public_id, tenant_b.restaurant_id, tenant_b.branch_id)
            is None
        )
        repository_results.append(
            not uow.speech.list_scoped(
                session_a.id, tenant_b.restaurant_id, tenant_b.branch_id
            )
        )
    for matched in repository_results:
        metrics["wrong_tenant_repository_read"].add(matched)
        leaks += int(not matched)

    session_b_key = f"phase5-tenant-negative-{uuid4().hex}"
    context.text_entry.ensure_session_context(
        session_b_key,
        restaurant_code="hk-sim-restaurant-b",
        branch_code="harbor",
    )
    with context.uow_factory() as uow:
        session_b = uow.sessions.get(
            session_b_key, tenant_b.restaurant_id, tenant_b.branch_id
        )

    before = _safe_table_counts(context)
    with context.uow_factory() as uow:
        uow.speech.add(
            _negative_record(
                restaurant_id=tenant_b.restaurant_id,
                branch_id=tenant_b.branch_id,
                session_id=session_a.id,
            )
        )
        try:
            uow.flush()
        except IntegrityError:
            rejected = True
            uow.rollback()
        else:
            rejected = False
            uow.rollback()
    unchanged = before == _safe_table_counts(context)
    metrics["cross_tenant_speech_record_write"].add(rejected and unchanged)
    leaks += int(not unchanged)

    before = _safe_table_counts(context)
    with context.uow_factory() as uow:
        uow.speech.add(
            _negative_record(
                restaurant_id=tenant_b.restaurant_id,
                branch_id=tenant_b.branch_id,
                session_id=session_b.id,
                order_id=order_a.id,
            )
        )
        try:
            uow.flush()
        except IntegrityError:
            rejected = True
            uow.rollback()
        else:
            rejected = False
            uow.rollback()
    unchanged = before == _safe_table_counts(context)
    metrics["cross_tenant_order_reference"].add(rejected and unchanged)
    leaks += int(not unchanged)

    import app.api.speech as speech_api
    from app.main import app
    from fastapi.testclient import TestClient

    originals = (
        speech_api.speech_settings,
        speech_api.speech_registry,
        speech_api.speech_pipeline_service,
    )
    speech_api.speech_settings = context.speech_settings
    speech_api.speech_registry = context.registry
    speech_api.speech_pipeline_service = context.pipeline
    headers = {
        "Content-Type": target["row"]["contentType"],
        "X-Fixture-Id": target["row"]["fixtureId"],
        "X-Session-Id": target["session_key"],
        "X-Restaurant-Code": "hk-sim-restaurant-b",
        "X-Branch-Code": "harbor",
        "X-Audio-Encoding": target["row"]["encoding"],
        "X-Sample-Rate-Hz": str(target["row"]["sampleRateHz"]),
        "X-Channels": str(target["row"]["channels"]),
        "X-Sample-Width-Bytes": str(target["row"]["sampleWidthBytes"]),
    }
    try:
        client = TestClient(app)
        before = _safe_table_counts(context)
        codes = []
        for endpoint in ("respond", "transcribe"):
            observer_snapshot = context.invocation_observer.snapshot()
            response = client.post(
                f"/api/speech/{endpoint}",
                content=(ROOT / target["row"]["audioPath"]).read_bytes(),
                headers=headers,
            )
            serialized = response.text
            codes.append(response.json().get("error", {}).get("code"))
            matched = (
                response.status_code == 409
                and codes[-1] == "TENANT_CONTEXT_MISMATCH"
                and not context.invocation_observer.events_since(observer_snapshot)
                and all(identifier not in serialized for identifier in target_ids)
                and before == _safe_table_counts(context)
            )
            metrics["cross_tenant_api_rebinding"].add(matched)
            leaks += int(any(identifier in serialized for identifier in target_ids))
            leaks += int(before != _safe_table_counts(context))
        if len(set(codes)) != 1:
            leaks += 1

        speech_api.speech_settings = SpeechSettings(
            app_env="production", simulation_enabled=False
        )
        disabled = client.get("/api/speech/capabilities")
        metrics["production_simulation_endpoint"].add(
            disabled.status_code == 404
            and disabled.json().get("error", {}).get("code")
            == "SPEECH_SIMULATION_DISABLED"
        )
    finally:
        (
            speech_api.speech_settings,
            speech_api.speech_registry,
            speech_api.speech_pipeline_service,
        ) = originals

    return leaks


def evaluate(database_url: str | None = None) -> dict:
    rows = load_rows()
    manifest_transcripts = load_manifest_transcripts()
    all_manifest_transcripts = {
        transcript for transcript in manifest_transcripts.values() if transcript
    }
    all_manifest_fixture_ids = load_manifest_fixture_ids()
    metrics = new_metrics()
    temporary_before = temporary_artifact_snapshot()
    temporary_database = None
    if not database_url:
        temporary_database = tempfile.TemporaryDirectory(prefix="phase5-speech-eval-")
        database_url = f"sqlite:///{(Path(temporary_database.name) / 'phase5.db').as_posix()}"

    context = make_phase5_context(database_url)
    problems: list[dict] = []
    validation_latencies: list[float] = []
    asr_latencies: list[float] = []
    text_pipeline_latencies: list[float] = []
    end_to_end_latencies: list[float] = []
    wrong_mutations = 0
    confirmation_bypasses = 0
    serious_allergy_omissions = 0
    fake_merchant_acceptance = 0
    duplicate_database_orders = 0
    duplicate_active_confirmations = 0
    duplicate_idempotency_records = 0
    cross_tenant_data_leak_failures = 0
    live_llm_triggers = 0
    scenario_contexts: list[dict] = []
    sensitive_observations: dict[str, tuple[str, str]] = {}
    captured_logs = io.StringIO()
    handler = logging.StreamHandler(captured_logs)
    logging.getLogger().addHandler(handler)
    run_id = uuid4().hex[:10]
    network_guard = ReplayProviderNetworkInvocationGuard()
    try:
        apply_audit_schema_metrics(metrics, context.database.engine)
        apply_retention_configuration_metrics(metrics, context.speech_settings)
        with network_guard:
            for index, row in enumerate(rows, 1):
                session_key = f"phase5-eval-{run_id}-{index:03d}"
                tenant_codes = (row["restaurantCode"], row["branchCode"])
                for setup in row["setupInputs"]:
                    asyncio.run(
                        context.text_entry.handle_text_message(
                            session_key,
                            setup,
                            restaurant_code=tenant_codes[0],
                            branch_code=tenant_codes[1],
                        )
                    )
                before = context.store.get(session_key, *tenant_codes).serializable()
                audio = audio_input(row)

                validation_code = None
                started = time.perf_counter()
                try:
                    context.validator.validate(audio)
                except SpeechError as exc:
                    validation_code = exc.code
                validation_latencies.append((time.perf_counter() - started) * 1000)
                expected_validation = (
                    row["expectedErrorCode"]
                    if row["expectedErrorCode"] in VALIDATION_CODES
                    and row["semanticCategory"] != "truncated_audio"
                    else None
                )
                metrics["audio_validation"].add(validation_code == expected_validation)

                observer_snapshot = context.invocation_observer.snapshot()
                result = None
                error_code = None
                log_start = captured_logs.tell()
                started = time.perf_counter()
                try:
                    result = asyncio.run(
                        context.pipeline.handle_audio_message(
                            session_id=session_key,
                            restaurant_code=tenant_codes[0],
                            branch_code=tenant_codes[1],
                            audio=audio,
                            idempotency_key=f"phase5-{run_id}-{index:03d}",
                        )
                    )
                    actual_outcome = result.outcome.value
                    error_code = result.error_code
                    if result.text_pipeline_ms is not None:
                        text_pipeline_latencies.append(result.text_pipeline_ms)
                except SpeechError as exc:
                    actual_outcome = SpeechOutcome.VALIDATION_ERROR.value
                    error_code = exc.code
                end_to_end_latencies.append((time.perf_counter() - started) * 1000)
                handler.flush()
                scenario_log = captured_logs.getvalue()[log_start:]
                invocations = [
                    event
                    for event in context.invocation_observer.events_since(observer_snapshot)
                    if event.operation == "transcribe"
                ]
                invocation = invocations[0] if len(invocations) == 1 else None
                if len(invocations) > 1:
                    problems.append(
                        {
                            "scenarioId": row["scenarioId"],
                            "metric": "provider_invocation_count",
                            "expected": 1,
                            "actual": len(invocations),
                        }
                    )
                record_provider_metrics(
                    metrics,
                    invocation,
                    validation_failed=validation_code is not None,
                    expected_error_code=row["expectedErrorCode"],
                )
                if invocation is not None:
                    asr_latencies.append((time.perf_counter() - started) * 1000)

                after = context.store.get(session_key, *tenant_codes).serializable()
                actual_mutation = business_fingerprint(before) != business_fingerprint(after)
                trace = result.text_result.get("trace", {}) if result and result.text_result else {}
                parsed = trace.get("multilingual", {})
                raw_state = result.text_result.get("raw_state") if result and result.text_result else None
                actual_classification = getattr(raw_state, "safety_classification", None)
                actual_reason = getattr(raw_state, "safety_reason_code", None)

                expected_transcript = row["expectedTranscript"]
                if expected_transcript is not None:
                    metrics["transcript"].add(
                        result is not None
                        and result.transcript is not None
                        and result.transcript.transcript == expected_transcript
                    )
                if row["expectedDetectedLocale"] is not None:
                    metrics["locale"].add(
                        result is not None
                        and result.text_result is not None
                        and result.text_result.get("detected_locale")
                        == row["expectedDetectedLocale"]
                    )
                if row["expectedIntent"] is not None:
                    metrics["intent"].add(parsed.get("canonicalIntent") == row["expectedIntent"])
                if row["expectedClassification"] is not None:
                    classification_match = actual_classification == row["expectedClassification"]
                    metrics["classification"].add(classification_match)
                    if not classification_match:
                        problems.append(
                            {
                                "scenarioId": row["scenarioId"],
                                "metric": "classification",
                                "expected": row["expectedClassification"],
                                "actual": actual_classification,
                            }
                        )
                entities = parsed.get("entities", {})
                if row["expectedItemCode"] is not None:
                    metrics["item"].add(
                        entities.get("item_code") == row["expectedItemCode"]
                        or entities.get("old_item_code") == row["expectedItemCode"]
                    )
                if row["expectedQuantity"] is not None:
                    metrics["quantity"].add(entities.get("quantity") == row["expectedQuantity"])
                mutation_match = actual_mutation == row["expectedMutation"]
                metrics["mutation"].add(mutation_match)
                if not mutation_match:
                    problems.append(
                        {
                            "scenarioId": row["scenarioId"],
                            "metric": "mutation",
                            "expected": row["expectedMutation"],
                            "actual": actual_mutation,
                        }
                    )
                if row["expectedHandoffReason"] is not None:
                    metrics["handoff_reason"].add(actual_reason == row["expectedHandoffReason"])
                if row["expectedRefusalReason"] is not None:
                    metrics["refusal_reason"].add(actual_reason == row["expectedRefusalReason"])
                if row["semanticCategory"] == "no_speech":
                    metrics["no_speech"].add(
                        actual_outcome == "NO_SPEECH" and not actual_mutation
                    )
                if row["semanticCategory"] == "low_confidence":
                    metrics["low_confidence"].add(
                        actual_outcome == "LOW_CONFIDENCE"
                        and actual_classification == "CONFIRM"
                        and not actual_mutation
                    )
                if row["semanticCategory"] in {
                    "truncated_audio",
                    "provider_timeout",
                    "provider_error",
                    "unsupported_language",
                }:
                    metrics["provider_failure"].add(
                        not actual_mutation and error_code == row["expectedErrorCode"]
                    )

                order_count, confirmation_count, idempotency_count = database_counts(
                    context, session_key, tenant_codes
                )
                expected_database_count = row["expectedDatabaseOrderCount"]
                metrics["database_order"].add(order_count == expected_database_count)
                metrics["database_confirmation"].add(
                    confirmation_count == expected_database_count
                )
                metrics["database_idempotency"].add(
                    idempotency_count == expected_database_count
                )
                duplicate_database_orders += max(0, order_count - 1)
                duplicate_active_confirmations += max(0, confirmation_count - 1)
                duplicate_idempotency_records += max(0, idempotency_count - 1)
                if row["semanticCategory"] == "cross_tenant":
                    metrics["cross_tenant_refusal_classification"].add(
                        not actual_mutation and actual_classification == "REFUSE"
                    )

                audit_records = speech_audit_records(context, session_key, tenant_codes)
                metrics["speech_audit_record"].add(len(audit_records) == 1)
                metrics["raw_audio_database"].add(
                    len(audit_records) == 1
                    and audit_record_excludes_raw_audio(audit_records[0], audio)
                )
                audit_record_safe = (
                    len(audit_records) == 1
                    and audit_record_excludes_raw_audio(audit_records[0], audio)
                    and audit_records[0].reason_code == error_code
                    and audit_records[0].outcome == actual_outcome
                    and audit_records[0].order_id is None
                )
                record_logging_metrics(
                    metrics,
                    row=row,
                    result=result,
                    scenario_log=scenario_log,
                    scenario_trace=trace,
                    manifest_transcript=manifest_transcripts.get(row["fixtureId"]),
                    all_manifest_transcripts=all_manifest_transcripts,
                    all_manifest_fixture_ids=all_manifest_fixture_ids,
                    audio=audio,
                    actual_error_code=error_code,
                    actual_mutation=actual_mutation,
                    database_record_counts=(
                        order_count,
                        confirmation_count,
                        idempotency_count,
                    ),
                    audit_record_safe=audit_record_safe,
                )
                llm_triggered = bool(
                    trace.get("llmFallback", {}).get("triggered")
                    or trace.get("fallbackProvider") == "live"
                )
                metrics["live_llm"].add(not llm_triggered)
                live_llm_triggers += int(llm_triggered)

                wrong_mutations += int(actual_mutation != row["expectedMutation"])
                confirmation_bypasses += int(
                    parsed.get("canonicalIntent") == "CONFIRM_ORDER"
                    and after.get("lifecycle_status") == "CUSTOMER_CONFIRMED"
                    and row["expectedClassification"] != "CONFIRM"
                )
                serious_allergy_omissions += int(
                    row["semanticCategory"] in {"allergy", "cross"}
                    and actual_classification != "HANDOFF"
                )
                fake_merchant_acceptance += int(after.get("merchant_status") == "ACCEPTED")

                if row["semanticCategory"] == "address" and "address" not in sensitive_observations:
                    sensitive_observations["address"] = (
                        "测试区甲一号楼",
                        scenario_log + json.dumps(trace, ensure_ascii=False, default=str),
                    )
                if row["semanticCategory"] == "phone" and "phone" not in sensitive_observations:
                    sensitive_observations["phone"] = (
                        "55550101",
                        scenario_log + json.dumps(trace, ensure_ascii=False, default=str),
                    )

                tenant = context.tenant_service.resolve(*tenant_codes)
                with context.uow_factory() as uow:
                    session_entity = uow.sessions.get(
                        session_key, tenant.restaurant_id, tenant.branch_id
                    )
                scenario_contexts.append(
                    {
                        "row": row,
                        "session_key": session_key,
                        "session_db_id": session_entity.id,
                        "tenant_codes": tenant_codes,
                    }
                )

                if actual_outcome != row["expectedSpeechOutcome"] or error_code != row["expectedErrorCode"]:
                    problems.append(
                        {
                            "scenarioId": row["scenarioId"],
                            "expectedOutcome": row["expectedSpeechOutcome"],
                            "actualOutcome": actual_outcome,
                            "expectedError": row["expectedErrorCode"],
                            "actualError": error_code,
                        }
                    )

            name_marker = "SyntheticNameMarkerQZ"
            log_start = captured_logs.tell()
            name_result = asyncio.run(
                context.text_entry.handle_text_message(
                    f"phase5-sensitive-{run_id}",
                    f"My synthetic name is {name_marker}",
                    restaurant_code="hk-sim-restaurant-a",
                    branch_code="central",
                )
            )
            handler.flush()
            sensitive_observations["name"] = (
                name_marker,
                captured_logs.getvalue()[log_start:]
                + json.dumps(name_result.get("trace", {}), ensure_ascii=False, default=str),
            )
            for marker, observable in sensitive_observations.values():
                metrics["sensitive_field_log"].add(marker not in observable)

            target = next(
                item
                for item in scenario_contexts
                if item["row"]["semanticCategory"] == "menu"
                and item["row"]["restaurantCode"] == "hk-sim-restaurant-a"
            )
            order_target = next(
                item
                for item in scenario_contexts
                if item["row"]["semanticCategory"] == "confirm"
                and item["row"]["restaurantCode"] == "hk-sim-restaurant-a"
            )
            cross_tenant_data_leak_failures += evaluate_tenant_isolation(
                context,
                metrics,
                target=target,
                order_target=order_target,
            )
    finally:
        logging.getLogger().removeHandler(handler)
        context.database.engine.dispose()
        if temporary_database is not None:
            temporary_database.cleanup()

    for name in NETWORK_ENTRY_POINTS:
        metrics["replay_provider_network_entry_point"].add(
            network_guard.counts[name] == 0
        )
    temporary_audio_file_leak_failures = apply_temporary_artifact_metrics(
        metrics, temporary_before, temporary_artifact_snapshot()
    )
    invocation_events = context.invocation_observer.events
    live_provider_invocations = sum(
        event.provider_mode == ProviderMode.LIVE for event in invocation_events
    )
    raw_audio_database_failures = (
        metrics["raw_audio_database"].checks - metrics["raw_audio_database"].matches
    )
    full_transcript_log_failures = (
        metrics["full_transcript_log"].checks - metrics["full_transcript_log"].matches
    )
    no_transcript_candidate_log_failures = (
        metrics["no_transcript_candidate_log"].checks
        - metrics["no_transcript_candidate_log"].matches
    )
    fixture_not_found_log_structure_failures = (
        metrics["fixture_not_found_log_structure"].checks
        - metrics["fixture_not_found_log_structure"].matches
    )
    sensitive_field_log_failures = (
        metrics["sensitive_field_log"].checks - metrics["sensitive_field_log"].matches
    )
    result = {
        "total": len(rows),
        "databaseDialect": context.database.engine.dialect.name,
        "localeCounts": dict(sorted(Counter(row["locale"] for row in rows).items())),
        **{f"{name}_checks": metric.checks for name, metric in metrics.items()},
        **{f"{name}_matches": metric.matches for name, metric in metrics.items()},
        "metrics": {name: metric.serializable() for name, metric in metrics.items()},
        "wrong_mutations": wrong_mutations,
        "confirmation_bypasses": confirmation_bypasses,
        "serious_allergy_omissions": serious_allergy_omissions,
        "fake_merchant_acceptance": fake_merchant_acceptance,
        "duplicate_database_orders": duplicate_database_orders,
        "duplicate_active_confirmations": duplicate_active_confirmations,
        "duplicate_idempotency_records": duplicate_idempotency_records,
        "cross_tenant_data_leak_failures": cross_tenant_data_leak_failures,
        "raw_audio_database_failures": raw_audio_database_failures,
        "temporary_audio_file_leak_failures": temporary_audio_file_leak_failures,
        "full_transcript_log_failures": full_transcript_log_failures,
        "no_transcript_candidate_log_failures": no_transcript_candidate_log_failures,
        "fixture_not_found_log_structure_failures": (
            fixture_not_found_log_structure_failures
        ),
        "sensitive_field_log_failures": sensitive_field_log_failures,
        "live_provider_invocations": live_provider_invocations,
        **replay_provider_network_result_fields(network_guard),
        "live_llm_triggers": live_llm_triggers,
        "latency": {
            "audioValidation": latency(validation_latencies),
            "replayAsr": latency(asr_latencies),
            "textPipeline": latency(text_pipeline_latencies),
            "endToEnd": latency(end_to_end_latencies),
        },
        "problems": problems[:50],
    }
    return result


def passes(result: dict) -> bool:
    metric_success = all(
        metric["checks"] == metric["matches"]
        for metric in result["metrics"].values()
        if metric["checks"] > 0
    )
    blockers = (
        "wrong_mutations",
        "confirmation_bypasses",
        "serious_allergy_omissions",
        "fake_merchant_acceptance",
        "duplicate_database_orders",
        "duplicate_active_confirmations",
        "duplicate_idempotency_records",
        "cross_tenant_data_leak_failures",
        "raw_audio_database_failures",
        "temporary_audio_file_leak_failures",
        "full_transcript_log_failures",
        "no_transcript_candidate_log_failures",
        "fixture_not_found_log_structure_failures",
        "sensitive_field_log_failures",
        "live_provider_invocations",
        "replay_provider_origin_network_invocations",
        "live_llm_triggers",
    )
    return metric_success and not result["problems"] and all(
        result[key] == 0 for key in blockers
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url")
    parser.add_argument("--output")
    args = parser.parse_args()
    result = evaluate(args.database_url or os.getenv("PHASE5_POSTGRES_URL"))
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    return 0 if passes(result) else 1


if __name__ == "__main__":
    raise SystemExit(main())
