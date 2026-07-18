from __future__ import annotations

import argparse
import asyncio
import io
import json
import logging
import math
import os
import tempfile
import time
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.phase5_harness import ROOT, make_phase5_context

from app.speech.contracts import AudioInput, SpeechRecognitionRequest
from app.speech.errors import SpeechError
from app.speech.formats import AudioEncoding, SpeechOutcome
from app.db.models import Order


DATASET = ROOT / "evaluation" / "phase5_speech_pipeline.jsonl"
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


def load_rows() -> list[dict]:
    return [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines()]


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


def database_order_count(context, session_key: str, tenant_codes: tuple[str, str]) -> int:
    tenant = context.tenant_service.resolve(*tenant_codes)
    with context.uow_factory() as uow:
        session = uow.sessions.get(session_key, tenant.restaurant_id, tenant.branch_id)
        if session is None:
            return 0
        return int(
            uow.session.scalar(
                select(func.count(Order.id)).where(
                    Order.session_id == session.id,
                    Order.restaurant_id == tenant.restaurant_id,
                    Order.branch_id == tenant.branch_id,
                )
            )
            or 0
        )


def speech_audit_count(context, session_key: str, tenant_codes: tuple[str, str]) -> int:
    tenant = context.tenant_service.resolve(*tenant_codes)
    with context.uow_factory() as uow:
        session = uow.sessions.get(session_key, tenant.restaurant_id, tenant.branch_id)
        if session is None:
            return 0
        return len(uow.speech.list_scoped(session.id, tenant.restaurant_id, tenant.branch_id))


def evaluate(database_url: str) -> dict:
    context = make_phase5_context(database_url)
    rows = load_rows()
    names = (
        "audio_validation",
        "fixture_hash",
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
        "database_order",
        "tenant_isolation",
        "audio_retention",
        "transcript_logging",
        "live_provider",
        "live_llm",
    )
    metrics = {name: Metric() for name in names}
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
    cross_tenant_leak_failures = 0
    raw_audio_persistence_failures = 0
    full_transcript_log_failures = 0
    live_provider_calls = 0
    live_llm_triggers = 0
    captured_logs = io.StringIO()
    handler = logging.StreamHandler(captured_logs)
    logging.getLogger().addHandler(handler)
    run_id = uuid4().hex[:10]
    try:
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

            provider_code = None
            if validation_code is None:
                started = time.perf_counter()
                try:
                    provider = context.registry.get_asr()
                    provider.transcribe(
                        SpeechRecognitionRequest(
                            audio=audio,
                            locale_hint=None,
                            session_id=session_key,
                            restaurant_code=tenant_codes[0],
                            branch_code=tenant_codes[1],
                            trace_id=f"SIM-PRECHECK-{index}",
                        )
                    )
                except SpeechError as exc:
                    provider_code = exc.code
                asr_latencies.append((time.perf_counter() - started) * 1000)
            expected_hash_failure = row["expectedErrorCode"] == "SPEECH_FIXTURE_HASH_MISMATCH"
            metrics["fixture_hash"].add(
                (provider_code == "SPEECH_FIXTURE_HASH_MISMATCH")
                if expected_hash_failure
                else provider_code != "SPEECH_FIXTURE_HASH_MISMATCH"
            )

            result = None
            error_code = None
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
                    and result.text_result.get("detected_locale") == row["expectedDetectedLocale"]
                )
            if row["expectedIntent"] is not None:
                metrics["intent"].add(parsed.get("canonicalIntent") == row["expectedIntent"])
            if row["expectedClassification"] is not None:
                classification_match = actual_classification == row["expectedClassification"]
                metrics["classification"].add(classification_match)
                if not classification_match:
                    problems.append({
                        "scenarioId": row["scenarioId"],
                        "metric": "classification",
                        "expected": row["expectedClassification"],
                        "actual": actual_classification,
                    })
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
                problems.append({
                    "scenarioId": row["scenarioId"],
                    "metric": "mutation",
                    "expected": row["expectedMutation"],
                    "actual": actual_mutation,
                })
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
                metrics["provider_failure"].add(not actual_mutation and error_code == row["expectedErrorCode"])

            order_count = database_order_count(context, session_key, tenant_codes)
            metrics["database_order"].add(order_count == row["expectedDatabaseOrderCount"])
            duplicate_database_orders += int(order_count > max(1, row["expectedDatabaseOrderCount"]))
            if row["semanticCategory"] == "cross_tenant":
                isolated = not actual_mutation and actual_classification == "REFUSE"
                metrics["tenant_isolation"].add(isolated)
                cross_tenant_leak_failures += int(not isolated)
            audit_ok = speech_audit_count(context, session_key, tenant_codes) == 1
            metrics["audio_retention"].add(audit_ok)
            raw_audio_persistence_failures += int(not audit_ok)
            metrics["transcript_logging"].add(True)
            provider_is_replay = result is None or result.transcript is None or result.transcript.provider_mode.value == "REPLAY"
            metrics["live_provider"].add(provider_is_replay)
            live_provider_calls += int(not provider_is_replay)
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
    finally:
        logging.getLogger().removeHandler(handler)
        context.database.engine.dispose()

    log_output = captured_logs.getvalue()
    for row in rows:
        transcript = row.get("expectedTranscript")
        if transcript and transcript in log_output:
            full_transcript_log_failures += 1
    metrics["transcript_logging"].matches -= min(
        metrics["transcript_logging"].matches,
        full_transcript_log_failures,
    )
    return {
        "total": len(rows),
        "localeCounts": dict(sorted(Counter(row["locale"] for row in rows).items())),
        **{f"{name}_checks": metric.checks for name, metric in metrics.items()},
        **{f"{name}_matches": metric.matches for name, metric in metrics.items()},
        "metrics": {name: metric.serializable() for name, metric in metrics.items()},
        "wrong_mutations": wrong_mutations,
        "confirmation_bypasses": confirmation_bypasses,
        "serious_allergy_omissions": serious_allergy_omissions,
        "fake_merchant_acceptance": fake_merchant_acceptance,
        "duplicate_database_orders": duplicate_database_orders,
        "cross_tenant_leak_failures": cross_tenant_leak_failures,
        "raw_audio_persistence_failures": raw_audio_persistence_failures,
        "full_transcript_log_failures": full_transcript_log_failures,
        "live_provider_calls": live_provider_calls,
        "live_llm_triggers": live_llm_triggers,
        "latency": {
            "audioValidation": latency(validation_latencies),
            "replayAsr": latency(asr_latencies),
            "textPipeline": latency(text_pipeline_latencies),
            "endToEnd": latency(end_to_end_latencies),
        },
        "problems": problems[:50],
    }


def passes(result: dict) -> bool:
    metric_success = all(
        metric["checks"] == metric["matches"]
        for metric in result["metrics"].values()
        if metric["checks"]
    )
    blockers = (
        "wrong_mutations",
        "confirmation_bypasses",
        "serious_allergy_omissions",
        "fake_merchant_acceptance",
        "duplicate_database_orders",
        "cross_tenant_leak_failures",
        "raw_audio_persistence_failures",
        "full_transcript_log_failures",
        "live_provider_calls",
        "live_llm_triggers",
    )
    return metric_success and not result["problems"] and all(result[key] == 0 for key in blockers)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url")
    parser.add_argument("--output")
    args = parser.parse_args()
    temporary = None
    database_url = args.database_url or os.getenv("PHASE5_POSTGRES_URL")
    if not database_url:
        temporary = tempfile.TemporaryDirectory(prefix="phase5-speech-eval-")
        database_url = f"sqlite:///{(Path(temporary.name) / 'phase5.db').as_posix()}"
    try:
        result = evaluate(database_url)
    finally:
        if temporary:
            temporary.cleanup()
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    return 0 if passes(result) else 1


if __name__ == "__main__":
    raise SystemExit(main())
