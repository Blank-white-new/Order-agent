from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

from experiments.common.io import read_jsonl, write_json, write_jsonl
from experiments.common.metadata import ROOT, collect_metadata, sha256_file
from experiments.common.offline import force_offline_environment
from experiments.token_efficiency_v2.quality_eval import (
    outcome_fingerprint,
    outcome_snapshot,
)


force_offline_environment("token-efficiency-v2-reference")
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from evaluation.run_phase4_multilingual_text_eval import create_service  # noqa: E402


DEFAULT_DATASET = ROOT / "experiments" / "datasets" / "token_conversations.jsonl"
DEFAULT_RESULTS = ROOT / "experiments" / "results" / "token_efficiency_v2"


async def build_reference(*, dataset_path: Path, results_dir: Path) -> dict:
    force_offline_environment("token-efficiency-v2-reference")
    conversations = read_jsonl(dataset_path)
    rows: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="token-v2-reference-") as temp_dir:
        runtime = create_service(
            f"sqlite:///{Path(temp_dir, 'quality-reference.db').as_posix()}"
        )
        try:
            for conversation in conversations:
                session_id = f"token-v2-reference-{conversation['conversation_id']}"
                for turn in conversation["turns"]:
                    before = runtime.service.ensure_session_context(
                        session_id,
                        restaurant_code=conversation["restaurant_code"],
                        branch_code=conversation["branch_code"],
                    ).serializable()
                    result = await runtime.service.handle_text_message(
                        session_id,
                        turn["user"],
                        restaurant_code=conversation["restaurant_code"],
                        branch_code=conversation["branch_code"],
                        idempotency_key=(
                            f"token-v2-reference-{conversation['conversation_id']}-"
                            f"{turn['turn_id']}"
                        ),
                    )
                    outcome = outcome_snapshot(result, before)
                    rows.append(
                        {
                            "conversation_id": conversation["conversation_id"],
                            "turn_id": turn["turn_id"],
                            "user_input_sha256": __import__("hashlib").sha256(
                                turn["user"].encode("utf-8")
                            ).hexdigest(),
                            "outcome": outcome,
                            "outcome_fingerprint": outcome_fingerprint(outcome),
                        }
                    )
        finally:
            runtime.database.engine.dispose()
    reference_path = results_dir / "quality_reference.jsonl"
    write_jsonl(reference_path, rows)
    metadata = collect_metadata(
        provider_mode="offline_validated_decision_reference",
        asr_provider="NOT_USED",
        tts_provider="NOT_USED",
        dataset_sha256=sha256_file(dataset_path),
        random_seed=42,
        warmup_count=0,
        measurement_count=len(rows),
        extra={
            "experiment": "token_efficiency_v2_quality_reference",
            "reference_path": str(reference_path.relative_to(ROOT)),
            "reference_sha256": sha256_file(reference_path),
            "expected_labels_passed_to_runtime": False,
            "live_llm_used": False,
            "reference_purpose": (
                "conversation-aware deterministic outcome replay; not an independent "
                "model-accuracy label"
            ),
        },
    )
    write_json(results_dir / "quality_reference_metadata.json", metadata)
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS)
    args = parser.parse_args()
    print(
        json.dumps(
            asyncio.run(
                build_reference(dataset_path=args.dataset, results_dir=args.results_dir)
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
