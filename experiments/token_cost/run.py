from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import tempfile
from pathlib import Path

from experiments.common.offline import force_offline_environment

# Set provider gates before importing the application graph. The helper also
# returns the effective configuration later for metadata.
force_offline_environment("token-cost")
BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.menu_service import MenuService
from evaluation.run_phase4_multilingual_text_eval import create_service
from experiments.common.io import read_jsonl, write_csv, write_json
from experiments.common.metadata import ROOT, collect_metadata, sha256_file
from experiments.token_cost.baseline import (
    TOKENIZER_DESCRIPTION,
    TOKENIZER_ID,
    build_prompt,
    compact_menu_snapshot,
    count_tokens,
    render_history,
)
from experiments.token_cost.current_architecture import summarize_runtime_result


DEFAULT_DATASET = ROOT / "experiments" / "datasets" / "token_conversations.jsonl"
DEFAULT_RESULTS = ROOT / "experiments" / "results" / "token_cost"


def _menu_context(runtime) -> str:
    tenant = runtime.tenant_service.resolve("hk-sim-restaurant-a", "central")
    with runtime.uow_factory() as uow:
        lexicon = uow.menus.multilingual_lexicon(tenant.branch_id)
    menu_service = MenuService(
        restaurant_code="hk-sim-restaurant-a",
        branch_code="central",
        database=runtime.database,
        locale="zh-CN",
    )
    priced = menu_service.all_items_as_dicts(include_unavailable=True)
    return compact_menu_snapshot(lexicon_rows=lexicon, priced_items=priced)


async def run_benchmark(*, run_id: int, dataset_path: Path, results_dir: Path) -> dict:
    force_offline_environment("token-cost")
    conversations = read_jsonl(dataset_path)
    results_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"order-token-{run_id}-") as temp_dir:
        database_url = f"sqlite:///{Path(temp_dir, 'token.db').as_posix()}"
        runtime = create_service(database_url)
        menu_snapshot = _menu_context(runtime)
        write_json(
            results_dir / "baseline_context_snapshot.json",
            {
                "restaurant_code": "hk-sim-restaurant-a",
                "branch_code": "central",
                "menu_snapshot": json.loads(menu_snapshot),
                "tokenizer_id": TOKENIZER_ID,
                "reconstruction": "Use experiments.token_cost.baseline.build_prompt with this menu and the preceding raw assistant responses.",
            },
        )
        raw_rows: list[dict] = []
        try:
            for conversation in conversations:
                history: list[dict[str, str]] = []
                session_id = f"token-r{run_id}-{conversation['conversation_id']}"
                for turn in conversation["turns"]:
                    prompt = build_prompt(
                        menu_snapshot=menu_snapshot,
                        history=history,
                        user_utterance=turn["user"],
                    )
                    result = await runtime.service.handle_text_message(
                        session_id,
                        turn["user"],
                        restaurant_code=conversation["restaurant_code"],
                        branch_code=conversation["branch_code"],
                        idempotency_key=f"token-r{run_id}-{conversation['conversation_id']}-{turn['turn_id']}",
                    )
                    current = summarize_runtime_result(result)
                    prompt_tokens = count_tokens(prompt)
                    rendered_history = render_history(history)
                    raw_rows.append(
                        {
                            "run_id": run_id,
                            "conversation_id": conversation["conversation_id"],
                            "turn_id": turn["turn_id"],
                            "scenario_type": conversation["scenario_type"],
                            "locale": conversation["locale"],
                            "source_scenario_id": conversation["source_scenario_ids"][turn["turn_id"] - 1],
                            "user_utterance": turn["user"],
                            "token_metric_scope": "projected_input_only",
                            "tokenizer_id": TOKENIZER_ID,
                            "baseline_input_tokens": prompt_tokens,
                            "baseline_output_token_budget": 0,
                            "baseline_total_projected_tokens": prompt_tokens,
                            "current_llm_required": current["current_llm_required"],
                            "current_input_tokens": current["current_input_tokens"],
                            "current_output_token_budget": current["current_output_token_budget"],
                            "current_total_projected_tokens": current["current_total_projected_tokens"],
                            "baseline_context_tokens": prompt_tokens,
                            "baseline_menu_tokens": count_tokens(menu_snapshot),
                            "baseline_history_tokens": count_tokens(rendered_history),
                            "baseline_current_utterance_tokens": count_tokens(turn["user"]),
                            "current_context_tokens": current["current_context_tokens"],
                            "baseline_llm_calls": 1,
                            "current_llm_calls": current["current_llm_calls"],
                            "canonical_intent": current["canonical_intent"],
                            "selected_handler": current["selected_handler"],
                            "decision_class": current["decision_class"],
                            "fallback_used": current["fallback_used"],
                            "execution_path": current["execution_path"],
                            "assistant_response": current["response"],
                            "baseline_prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                        }
                    )
                    history.append({"user": turn["user"], "assistant": current["response"]})
        finally:
            runtime.database.engine.dispose()

    raw_path = results_dir / f"run_{run_id}_raw.csv"
    write_csv(raw_path, raw_rows)
    metadata = collect_metadata(
        provider_mode="offline_deterministic_text",
        asr_provider="NOT_USED",
        tts_provider="NOT_USED",
        dataset_sha256=sha256_file(dataset_path),
        random_seed=42,
        warmup_count=0,
        measurement_count=len(raw_rows),
        extra={
            "run_id": run_id,
            "experiment": "token_cost",
            "metric_scope": "projected_input_only",
            "tokenizer_id": TOKENIZER_ID,
            "tokenizer_description": TOKENIZER_DESCRIPTION,
            "raw_csv": str(raw_path.relative_to(ROOT)),
            "raw_csv_sha256": sha256_file(raw_path),
            "offline_environment": {
                "ALLOW_LIVE_LLM": "false",
                "LLM_FALLBACK_MODE": "disabled",
                "VOICE_ENABLED": "false",
                "TTS_ENABLED": "false",
            },
            "baseline_prompt_saved_per_turn": False,
            "baseline_prompt_reconstructable": True,
            "ground_truth_fields_passed_to_runtime": False,
        },
    )
    write_json(results_dir / f"run_{run_id}_metadata.json", metadata)
    summary = {
        "run_id": run_id,
        "conversations": len(conversations),
        "turns": len(raw_rows),
        "baseline_input_tokens": sum(row["baseline_input_tokens"] for row in raw_rows),
        "current_input_tokens": sum(row["current_input_tokens"] for row in raw_rows),
        "baseline_llm_calls": sum(row["baseline_llm_calls"] for row in raw_rows),
        "current_llm_calls": sum(row["current_llm_calls"] for row in raw_rows),
        "dataset_sha256": sha256_file(dataset_path),
    }
    write_json(results_dir / f"run_{run_id}_summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", type=int, required=True, choices=(1, 2, 3))
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run_benchmark(run_id=args.run_id, dataset_path=args.dataset, results_dir=args.results_dir)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
