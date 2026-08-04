from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from time import perf_counter_ns

from experiments.common.io import read_jsonl, write_csv, write_json
from experiments.common.metadata import ROOT, collect_metadata, sha256_file, sha256_paths
from experiments.common.offline import force_offline_environment


force_offline_environment("local-decision-latency")
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from evaluation.run_phase4_multilingual_text_eval import create_service  # noqa: E402


PHASE4 = ROOT / "evaluation" / "phase4_multilingual_text.jsonl"
CONVERSATIONS = ROOT / "experiments" / "datasets" / "token_conversations.jsonl"
DEFAULT_RESULTS = ROOT / "experiments" / "results" / "latency"
SAFETY_CATEGORIES = {
    "allergy", "attack", "bypass", "card", "complaint", "cross", "cross_tenant",
    "dispute", "forge", "guarantee", "human", "other_order", "refund", "secret",
}
AMBIGUITY_CATEGORIES = {
    "ambiguous_item", "ambiguous_quantity", "bad_modifier", "correction", "missing_item",
    "question_add", "sold_out", "unsupported",
}


def category_group(semantic_category: str) -> str:
    if semantic_category in SAFETY_CATEGORIES:
        return "safety"
    if semantic_category in AMBIGUITY_CATEGORIES:
        return "ambiguity"
    return "routine"


def build_measurements() -> list[dict]:
    rows = []
    phase4_rows = read_jsonl(PHASE4)
    category_by_id = {source["scenario_id"]: source["semantic_category"] for source in phase4_rows}
    for source in phase4_rows:
        rows.append(
            {
                "case_id": f"text-phase4-{source['scenario_id']}",
                "dataset_source": "phase4_single_turn",
                "conversation_id": source["scenario_id"],
                "turn_id": 1,
                "locale": source["locale"],
                "semantic_category": source["semantic_category"],
                "category_group": category_group(source["semantic_category"]),
                "text": source["input"],
                "setup_inputs": list(source.get("setup_inputs") or []),
                "restaurant_code": source["restaurant_code"],
                "branch_code": source["branch_code"],
            }
        )
    for conversation in read_jsonl(CONVERSATIONS):
        for turn in conversation["turns"]:
            source_id = conversation["source_scenario_ids"][turn["turn_id"] - 1]
            semantic_category = category_by_id[source_id]
            rows.append(
                {
                    "case_id": f"text-conversation-{conversation['conversation_id']}-{turn['turn_id']:02d}",
                    "dataset_source": "complete_conversation",
                    "conversation_id": conversation["conversation_id"],
                    "turn_id": turn["turn_id"],
                    "locale": conversation["locale"],
                    "semantic_category": semantic_category,
                    "category_group": category_group(semantic_category),
                    "text": turn["user"],
                    "setup_inputs": [],
                    "restaurant_code": conversation["restaurant_code"],
                    "branch_code": conversation["branch_code"],
                }
            )
    return rows


def _result_fields(result: dict) -> dict:
    trace = result.get("trace") or {}
    safety = trace.get("safety") or {}
    state = result.get("state") or {}
    return {
        "canonical_intent": trace.get("finalIntent") or (trace.get("interpretation") or {}).get("intent") or "",
        "selected_handler": trace.get("selectedHandler") or "",
        "decision_class": safety.get("classification") or state.get("safety_classification") or "",
        "response_sha256": __import__("hashlib").sha256(str(result.get("response") or "").encode("utf-8")).hexdigest(),
        "state_sha256": __import__("hashlib").sha256(json.dumps(state, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest(),
    }


async def run_benchmark(*, run_id: int, results_dir: Path, warmup_count: int = 20) -> dict:
    force_offline_environment("local-decision-latency")
    measurements = build_measurements()
    results_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"order-text-latency-{run_id}-") as temp_dir:
        runtime = create_service(f"sqlite:///{Path(temp_dir, 'latency.db').as_posix()}")
        raw: list[dict] = []
        try:
            # Imports, migrations, fixture reads, and warm-up are all outside the timed region.
            for index in range(warmup_count):
                sample = measurements[index % len(measurements)]
                await runtime.service.handle_text_message(
                    f"text-warmup-r{run_id}-{index}",
                    sample["text"],
                    restaurant_code=sample["restaurant_code"],
                    branch_code=sample["branch_code"],
                    idempotency_key=f"text-warmup-r{run_id}-{index}",
                )

            active_conversation = None
            active_session = None
            for index, sample in enumerate(measurements, start=1):
                if sample["dataset_source"] == "complete_conversation":
                    if sample["conversation_id"] != active_conversation:
                        active_conversation = sample["conversation_id"]
                        active_session = f"text-r{run_id}-{active_conversation}"
                    session_id = active_session
                else:
                    session_id = f"text-r{run_id}-{sample['case_id']}"
                    for setup_index, setup in enumerate(sample["setup_inputs"]):
                        await runtime.service.handle_text_message(
                            session_id,
                            setup,
                            restaurant_code=sample["restaurant_code"],
                            branch_code=sample["branch_code"],
                            idempotency_key=f"text-setup-r{run_id}-{index}-{setup_index}",
                        )
                started = perf_counter_ns()
                result = await runtime.service.handle_text_message(
                    session_id,
                    sample["text"],
                    restaurant_code=sample["restaurant_code"],
                    branch_code=sample["branch_code"],
                    idempotency_key=f"text-measured-r{run_id}-{index}",
                )
                elapsed_ns = perf_counter_ns() - started
                raw.append(
                    {
                        "run_id": run_id,
                        **{key: value for key, value in sample.items() if key not in {"setup_inputs"}},
                        **_result_fields(result),
                        "latency_ns": elapsed_ns,
                        "latency_ms": elapsed_ns / 1_000_000,
                        "timer": "time.perf_counter_ns",
                    }
                )
        finally:
            runtime.database.engine.dispose()

    raw_path = results_dir / f"text_run_{run_id}_raw.csv"
    write_csv(raw_path, raw)
    combined_dataset_hash = sha256_paths((PHASE4, CONVERSATIONS))
    metadata = collect_metadata(
        dataset_sha256=combined_dataset_hash,
        random_seed=42,
        warmup_count=warmup_count,
        measurement_count=len(raw),
        provider_mode="offline_local_decision_sqlite",
        asr_provider="NOT_USED",
        tts_provider="NOT_USED",
        extra={
            "run_id": run_id,
            "experiment": "local_decision_latency",
            "timer": "time.perf_counter_ns",
            "database": "SQLite (temporary per run)",
            "timed_region": "await TextEntryService.handle_text_message only",
            "excluded": ["Python startup", "imports", "migration", "seeding", "fixture loading", "warmup", "setup inputs", "logging"],
            "raw_csv": str(raw_path.relative_to(ROOT)),
            "raw_csv_sha256": sha256_file(raw_path),
            "ground_truth_fields_passed_to_runtime": False,
        },
    )
    write_json(results_dir / f"text_run_{run_id}_metadata.json", metadata)
    summary_payload = {"run_id": run_id, "measurement_count": len(raw), "warmup_count": warmup_count, "raw_csv_sha256": sha256_file(raw_path)}
    write_json(results_dir / f"text_run_{run_id}_summary.json", summary_payload)
    return summary_payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", type=int, required=True, choices=(1, 2, 3))
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--warmup-count", type=int, default=20)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run_benchmark(run_id=args.run_id, results_dir=args.results_dir, warmup_count=args.warmup_count)), indent=2))


if __name__ == "__main__":
    main()
