from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.phase5_harness import ROOT, make_phase5_context

from app.speech.contracts import AudioInput
from app.speech.errors import SpeechError
from app.speech.formats import AudioEncoding, ProviderMode


MANIFEST = ROOT / "evaluation" / "audio" / "manifests" / "phase5_tts_manifest.jsonl"
TENANT = ("hk-sim-restaurant-a", "central")


def rows() -> list[dict]:
    return [json.loads(line) for line in MANIFEST.read_text(encoding="utf-8").splitlines()]


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1)
    return round(ordered[index], 3)


def audit_count(context, session_key: str) -> int:
    tenant = context.tenant_service.resolve(*TENANT)
    with context.uow_factory() as uow:
        session = uow.sessions.get(session_key, tenant.restaurant_id, tenant.branch_id)
        return len(uow.speech.list_scoped(session.id, tenant.restaurant_id, tenant.branch_id))


def evaluate(database_url: str) -> dict:
    context = make_phase5_context(database_url)
    metrics = {
        name: {"checks": 0, "matches": 0}
        for name in (
            "locale", "voice_id", "text_hash", "fixture", "wav", "sample_rate",
            "mono", "duration", "audio_hash", "provider_mode", "network",
            "order_unchanged", "audit", "missing_fixture_failure",
        )
    }
    latencies = []
    failures = []

    def add(name: str, matched: bool) -> None:
        metrics[name]["checks"] += 1
        metrics[name]["matches"] += int(bool(matched))

    try:
        for index, row in enumerate(rows(), 1):
            session_key = f"phase5-tts-{uuid4().hex}"
            before = context.text_entry.ensure_session_context(
                session_key,
                restaurant_code=TENANT[0],
                branch_code=TENANT[1],
            ).serializable()
            started = time.perf_counter()
            result = context.pipeline.synthesize(
                text=row["text"],
                locale=row["locale"],
                voice_id=row["voiceId"],
                output_encoding=AudioEncoding(row["encoding"]),
                sample_rate_hz=row["sampleRateHz"],
                session_id=session_key,
                restaurant_code=TENANT[0],
                branch_code=TENANT[1],
            )
            latencies.append((time.perf_counter() - started) * 1000)
            validated = context.validator.validate(
                AudioInput(
                    payload=result.payload,
                    content_type=result.content_type,
                    encoding=result.encoding,
                    sample_rate_hz=result.sample_rate_hz,
                    channels=1,
                    sample_width_bytes=2,
                    synthetic=True,
                )
            )
            after = context.store.get(session_key, *TENANT).serializable()
            add("locale", row["locale"] in context.registry.get_tts().capabilities().locales)
            add("voice_id", row["voiceId"] in context.registry.get_tts().capabilities().voice_ids)
            add("text_hash", hashlib.sha256(row["text"].encode("utf-8")).hexdigest() == row["textSha256"])
            add("fixture", len(result.payload) > 44)
            add("wav", result.payload[:4] == b"RIFF" and result.payload[8:12] == b"WAVE")
            add("sample_rate", validated.sample_rate_hz == row["sampleRateHz"])
            add("mono", validated.channels == 1)
            add("duration", validated.duration_ms == row["durationMs"])
            add("audio_hash", hashlib.sha256(result.payload).hexdigest() == row["sha256"])
            add("provider_mode", result.provider_mode == ProviderMode.REPLAY)
            add("network", context.registry.get_tts().capabilities().requires_network is False)
            add("order_unchanged", before == after)
            add("audit", audit_count(context, session_key) == 1)

        failure_session = f"phase5-tts-missing-{uuid4().hex}"
        before = context.text_entry.ensure_session_context(
            failure_session,
            restaurant_code=TENANT[0],
            branch_code=TENANT[1],
        ).serializable()
        try:
            context.pipeline.synthesize(
                text="uncatalogued synthetic reply",
                locale="en-HK",
                session_id=failure_session,
                restaurant_code=TENANT[0],
                branch_code=TENANT[1],
            )
        except SpeechError as exc:
            missing_ok = exc.code == "TTS_FIXTURE_NOT_FOUND"
        else:
            missing_ok = False
        after = context.store.get(failure_session, *TENANT).serializable()
        add("missing_fixture_failure", missing_ok and before == after)
    except Exception as exc:
        failures.append({"type": type(exc).__name__, "detail": str(exc)[:160]})
    finally:
        context.database.engine.dispose()

    for metric in metrics.values():
        metric["rate"] = (
            "not_evaluated" if metric["checks"] == 0 else metric["matches"] / metric["checks"]
        )
    return {
        "total": len(rows()),
        "metrics": metrics,
        "latency": {
            "replayTts": {
                "count": len(latencies),
                "p50Ms": percentile(latencies, 0.50),
                "p95Ms": percentile(latencies, 0.95),
                "maxMs": round(max(latencies), 3),
            }
        },
        "naturalness": "not_evaluated",
        "intelligibility": "not_evaluated",
        "realTtsAccuracy": "not_evaluated",
        "liveProviderCalls": 0,
        "orderMutations": 0 if metrics["order_unchanged"]["matches"] == metrics["order_unchanged"]["checks"] else 1,
        "failures": failures,
    }


def passes(result: dict) -> bool:
    return (
        not result["failures"]
        and result["liveProviderCalls"] == 0
        and result["orderMutations"] == 0
        and all(value["checks"] == value["matches"] for value in result["metrics"].values())
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url")
    args = parser.parse_args()
    temporary = None
    database_url = args.database_url or os.getenv("PHASE5_POSTGRES_URL")
    if not database_url:
        temporary = tempfile.TemporaryDirectory(prefix="phase5-tts-eval-")
        database_url = f"sqlite:///{(Path(temporary.name) / 'phase5.db').as_posix()}"
    try:
        result = evaluate(database_url)
    finally:
        if temporary:
            temporary.cleanup()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if passes(result) else 1


if __name__ == "__main__":
    raise SystemExit(main())
