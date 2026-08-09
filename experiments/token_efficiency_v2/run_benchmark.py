from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from experiments.common.io import read_jsonl, write_csv, write_json
from experiments.common.metadata import ROOT, collect_metadata, sha256_file
from experiments.common.offline import force_offline_environment
from experiments.token_efficiency_v2.audit_dataset import template_group_id
from experiments.token_efficiency_v2.baseline import build_baseline_request
from experiments.token_efficiency_v2.quality_eval import (
    DecisionReplayProvider,
    evaluate_turn_quality,
    outcome_fingerprint,
    outcome_snapshot,
)
from experiments.token_efficiency_v2.selective_llm import (
    decide_selective_invocation,
    selective_prompt_sections,
)
from experiments.token_efficiency_v2.tokenizer import (
    count_messages,
    count_text,
    metadata as tokenizer_metadata,
    prompt_sha256,
)


force_offline_environment("token-efficiency-v2")
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.llm_fallback_prompt import (  # noqa: E402
    SYSTEM_PROMPT as SELECTIVE_SYSTEM_PROMPT,
    build_llm_fallback_prompt,
    recall_menu_candidates,
)
from app.services.menu_service import MenuService  # noqa: E402
from evaluation.run_phase4_multilingual_text_eval import create_service  # noqa: E402


DEFAULT_DATASET = ROOT / "experiments" / "datasets" / "token_conversations.jsonl"
PHASE4_SOURCE = ROOT / "evaluation" / "phase4_multilingual_text.jsonl"
DEFAULT_RESULTS = ROOT / "experiments" / "results" / "token_efficiency_v2"
DEFAULT_REFERENCE = DEFAULT_RESULTS / "quality_reference.jsonl"


def _reference_map(path: Path) -> dict[tuple[str, int], dict[str, Any]]:
    return {
        (row["conversation_id"], int(row["turn_id"])): row["outcome"]
        for row in read_jsonl(path)
    }


def _phase4_map() -> dict[str, dict[str, Any]]:
    return {row["scenario_id"]: row for row in read_jsonl(PHASE4_SOURCE)}


def _menu_service(runtime, conversation: dict[str, Any]) -> MenuService:
    locale = conversation["locale"] if conversation["locale"] != "mixed" else "en-HK"
    return MenuService(
        restaurant_code=conversation["restaurant_code"],
        branch_code=conversation["branch_code"],
        database=runtime.database,
        locale=locale,
    )


def _section_counts(messages: list[dict[str, str]], sections: dict[str, str]) -> dict[str, int]:
    message_count = count_messages(messages)
    selected = {
        "system_tokens": count_text(sections.get("system", "")),
        "restaurant_context_tokens": count_text(sections.get("restaurant", "")),
        "menu_context_tokens": count_text(sections.get("menu", "")),
        "policy_context_tokens": count_text(sections.get("policy", "")),
        "history_tokens": count_text(sections.get("history", "")),
        "current_input_tokens": count_text(sections.get("current_input", "")),
    }
    selected["component_token_sum"] = sum(selected.values())
    selected["message_content_tokens"] = message_count.content
    selected["message_framing_tokens"] = message_count.framing
    selected["message_count"] = message_count.message_count
    selected["input_tokens"] = message_count.total
    selected["other_or_boundary_tokens"] = message_count.total - selected[
        "component_token_sum"
    ]
    return selected


def _zero_counts() -> dict[str, int]:
    return {
        "system_tokens": 0,
        "restaurant_context_tokens": 0,
        "menu_context_tokens": 0,
        "policy_context_tokens": 0,
        "history_tokens": 0,
        "current_input_tokens": 0,
        "component_token_sum": 0,
        "message_content_tokens": 0,
        "message_framing_tokens": 0,
        "message_count": 0,
        "input_tokens": 0,
        "other_or_boundary_tokens": 0,
    }


def _row(
    *,
    run_id: int,
    architecture: str,
    conversation: dict[str, Any],
    turn: dict[str, Any],
    source: dict[str, Any],
    template_id: str,
    invoked: bool,
    invocation_reason: str,
    counts: dict[str, int],
    cumulative_tokens: int,
    prompt_hash: str,
    quality: dict[str, Any],
    outcome: dict[str, Any],
    pair_match: bool,
    replay_used: bool,
    replay_matches_runtime: bool | None,
    context_mode: str,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "conversation_id": conversation["conversation_id"],
        "turn_id": turn["turn_id"],
        "locale": conversation["locale"],
        "scenario_type": conversation["scenario_type"],
        "semantic_category": source["semantic_category"],
        "template_group_id": template_id,
        "source_scenario_id": source["scenario_id"],
        "user_utterance": turn["user"],
        "architecture": architecture,
        "LLM_invoked": invoked,
        "invocation_reason": invocation_reason,
        "input_tokens": counts["input_tokens"],
        "output_tokens": 0,
        "output_token_status": "NOT_MEASURED",
        "total_tokens": counts["input_tokens"],
        "cumulative_tokens": cumulative_tokens,
        "history_tokens": counts["history_tokens"],
        "menu_context_tokens": counts["menu_context_tokens"],
        "policy_context_tokens": counts["policy_context_tokens"],
        "current_input_tokens": counts["current_input_tokens"],
        "system_tokens": counts["system_tokens"],
        "restaurant_context_tokens": counts["restaurant_context_tokens"],
        "message_content_tokens": counts["message_content_tokens"],
        "message_framing_tokens": counts["message_framing_tokens"],
        "message_count": counts["message_count"],
        "component_token_sum": counts["component_token_sum"],
        "other_or_boundary_tokens": counts["other_or_boundary_tokens"],
        "context_mode": context_mode,
        "prompt_sha256": prompt_hash,
        "replay_output_used": replay_used,
        "replay_matches_runtime": replay_matches_runtime
        if replay_matches_runtime is not None
        else "",
        "canonical_intent": outcome["canonical_intent"],
        "decision_class": outcome["classification"],
        "selected_handler": outcome["selected_handler"],
        "observed_mutation": outcome["mutation"],
        "source_expected_classification": source.get("expected_classification"),
        "source_classification_match": outcome["classification"]
        == source.get("expected_classification"),
        "source_expected_mutation": source.get("expected_mutation"),
        "source_mutation_match": outcome["mutation"]
        == source.get("expected_mutation"),
        "intent_correct": quality["intent_correct"],
        "locale_correct": quality["locale_correct"],
        "item_checked": quality["item_checked"],
        "item_correct": quality["item_correct"],
        "quantity_checked": quality["quantity_checked"],
        "quantity_correct": quality["quantity_correct"],
        "modifier_checked": quality["modifier_checked"],
        "modifier_correct": quality["modifier_correct"],
        "mutation_reference_correct": quality["mutation_reference_correct"],
        "blocking_safety_checked": quality["blocking_safety_checked"],
        "blocking_safety_correct": quality["blocking_safety_correct"],
        "confirmation_bypass": quality["confirmation_bypass"],
        "serious_allergy_omission": quality["serious_allergy_omission"],
        "false_merchant_acceptance": quality["false_merchant_acceptance"],
        "duplicate_line_identity": quality["duplicate_line_identity"],
        "duplicate_mutation": quality["duplicate_mutation"],
        "blocking_safety_violations": quality["blocking_safety_violations"],
        "expected_path_correct": quality["expected_path_correct"],
        "architecture_pair_outcome_match": pair_match,
        "outcome_fingerprint": quality["outcome_fingerprint"],
    }


async def run_benchmark(
    *,
    run_id: int,
    dataset_path: Path,
    reference_path: Path,
    results_dir: Path,
) -> dict[str, Any]:
    force_offline_environment(f"token-efficiency-v2-run-{run_id}")
    conversations = read_jsonl(dataset_path)
    expected_by_id = _phase4_map()
    reference_by_key = _reference_map(reference_path)
    provider = DecisionReplayProvider(reference_by_key)
    raw_rows: list[dict[str, Any]] = []
    prompt_examples: dict[str, dict[str, Any]] = {}
    totals: dict[str, dict[str, int]] = defaultdict(
        lambda: {"input_tokens": 0, "llm_calls": 0}
    )

    with tempfile.TemporaryDirectory(prefix=f"token-v2-run-{run_id}-") as temp_dir:
        runtime_a = create_service(
            f"sqlite:///{Path(temp_dir, 'baseline-a.db').as_posix()}"
        )
        runtime_b = create_service(
            f"sqlite:///{Path(temp_dir, 'system-b.db').as_posix()}"
        )
        try:
            for conversation in conversations:
                history_a: list[dict[str, str]] = []
                cumulative = {"baseline_a": 0, "system_b": 0}
                template_key = ">".join(
                    expected_by_id[source_id]["semantic_category"]
                    for source_id in conversation["source_scenario_ids"]
                )
                template_id = template_group_id(template_key)
                session_a = f"token-v2-a-r{run_id}-{conversation['conversation_id']}"
                session_b = f"token-v2-b-r{run_id}-{conversation['conversation_id']}"
                menu_a = _menu_service(runtime_a, conversation)
                menu_b = _menu_service(runtime_b, conversation)
                all_menu = menu_a.all_items_as_dicts(include_unavailable=True)

                for turn, source_id in zip(
                    conversation["turns"], conversation["source_scenario_ids"]
                ):
                    key = (conversation["conversation_id"], int(turn["turn_id"]))
                    reference = reference_by_key[key]
                    before_a = runtime_a.service.ensure_session_context(
                        session_a,
                        restaurant_code=conversation["restaurant_code"],
                        branch_code=conversation["branch_code"],
                    ).serializable()
                    before_b_state = runtime_b.service.ensure_session_context(
                        session_b,
                        restaurant_code=conversation["restaurant_code"],
                        branch_code=conversation["branch_code"],
                    )
                    before_b = before_b_state.serializable()

                    candidates = recall_menu_candidates(
                        turn["user"], menu_a, limit=5
                    )
                    request_a = build_baseline_request(
                        user_utterance=turn["user"],
                        history=history_a,
                        restaurant_code=conversation["restaurant_code"],
                        branch_code=conversation["branch_code"],
                        locale=conversation["locale"],
                        menu_items=all_menu,
                        candidate_items=candidates,
                    )
                    counts_a = _section_counts(request_a.messages, request_a.sections)
                    prompt_hash_a = prompt_sha256(request_a.messages)

                    result_a = await runtime_a.service.handle_text_message(
                        session_a,
                        turn["user"],
                        restaurant_code=conversation["restaurant_code"],
                        branch_code=conversation["branch_code"],
                        idempotency_key=(
                            f"token-v2-a-r{run_id}-{conversation['conversation_id']}-"
                            f"{turn['turn_id']}"
                        ),
                    )
                    result_b = await runtime_b.service.handle_text_message(
                        session_b,
                        turn["user"],
                        restaurant_code=conversation["restaurant_code"],
                        branch_code=conversation["branch_code"],
                        idempotency_key=(
                            f"token-v2-b-r{run_id}-{conversation['conversation_id']}-"
                            f"{turn['turn_id']}"
                        ),
                    )

                    decision_b = decide_selective_invocation(result_b)
                    messages_b: list[dict[str, str]] = []
                    sections_b: dict[str, str] = {}
                    if decision_b.invoked:
                        fallback_prompt = build_llm_fallback_prompt(
                            turn["user"], before_b_state, menu_b, top_n=8
                        )
                        messages_b = [
                            {"role": "system", "content": SELECTIVE_SYSTEM_PROMPT},
                            {"role": "user", "content": fallback_prompt},
                        ]
                        sections_b = selective_prompt_sections(
                            fallback_prompt, SELECTIVE_SYSTEM_PROMPT
                        )
                        counts_b = _section_counts(messages_b, sections_b)
                        prompt_hash_b = prompt_sha256(messages_b)
                    else:
                        counts_b = _zero_counts()
                        prompt_hash_b = ""

                    # Evaluation labels are loaded only after prompts and runtime
                    # outputs exist. They are not accepted by either builder.
                    source = expected_by_id[source_id]
                    quality_a = evaluate_turn_quality(
                        result=result_a,
                        before_state=before_a,
                        source_expected=source,
                        reference_outcome=reference,
                    )
                    quality_b = evaluate_turn_quality(
                        result=result_b,
                        before_state=before_b,
                        source_expected=source,
                        reference_outcome=reference,
                    )
                    outcome_a = quality_a["outcome"]
                    outcome_b = quality_b["outcome"]
                    pair_match = outcome_fingerprint(outcome_a) == outcome_fingerprint(
                        outcome_b
                    )

                    replay_a = provider.invoke(
                        conversation_id=conversation["conversation_id"],
                        turn_id=turn["turn_id"],
                        prompt_sha256=prompt_hash_a,
                    )
                    replay_a_match = outcome_fingerprint(replay_a) == outcome_fingerprint(
                        outcome_a
                    )
                    replay_b_match: bool | None = None
                    if decision_b.invoked:
                        replay_b = provider.invoke(
                            conversation_id=conversation["conversation_id"],
                            turn_id=turn["turn_id"],
                            prompt_sha256=prompt_hash_b,
                        )
                        replay_b_match = outcome_fingerprint(
                            replay_b
                        ) == outcome_fingerprint(outcome_b)

                    cumulative["baseline_a"] += counts_a["input_tokens"]
                    cumulative["system_b"] += counts_b["input_tokens"]
                    totals["baseline_a"]["input_tokens"] += counts_a["input_tokens"]
                    totals["baseline_a"]["llm_calls"] += 1
                    totals["system_b"]["input_tokens"] += counts_b["input_tokens"]
                    totals["system_b"]["llm_calls"] += int(decision_b.invoked)

                    raw_rows.append(
                        _row(
                            run_id=run_id,
                            architecture="baseline_a",
                            conversation=conversation,
                            turn=turn,
                            source=source,
                            template_id=template_id,
                            invoked=True,
                            invocation_reason="direct_llm_every_turn",
                            counts=counts_a,
                            cumulative_tokens=cumulative["baseline_a"],
                            prompt_hash=prompt_hash_a,
                            quality=quality_a,
                            outcome=outcome_a,
                            pair_match=pair_match,
                            replay_used=True,
                            replay_matches_runtime=replay_a_match,
                            context_mode=request_a.menu_mode,
                        )
                    )
                    raw_rows.append(
                        _row(
                            run_id=run_id,
                            architecture="system_b",
                            conversation=conversation,
                            turn=turn,
                            source=source,
                            template_id=template_id,
                            invoked=decision_b.invoked,
                            invocation_reason=decision_b.reason,
                            counts=counts_b,
                            cumulative_tokens=cumulative["system_b"],
                            prompt_hash=prompt_hash_b,
                            quality=quality_b,
                            outcome=outcome_b,
                            pair_match=pair_match,
                            replay_used=decision_b.invoked,
                            replay_matches_runtime=replay_b_match,
                            context_mode=(
                                "production_compact_fallback_prompt"
                                if decision_b.invoked
                                else "no_llm_context"
                            ),
                        )
                    )

                    if run_id == 1:
                        example_key = None
                        if source["semantic_category"] == "add1" and "routine" not in prompt_examples:
                            example_key = "routine"
                        elif (
                            conversation["scenario_type"] == "complex"
                            and decision_b.invoked
                            and "complex" not in prompt_examples
                        ):
                            example_key = "complex"
                        elif source["semantic_category"] == "allergy" and "safety" not in prompt_examples:
                            example_key = "safety"
                        if example_key:
                            prompt_examples[example_key] = {
                                "conversation_id": conversation["conversation_id"],
                                "turn_id": turn["turn_id"],
                                "user_utterance": turn["user"],
                                "baseline_a": {
                                    "messages": request_a.messages,
                                    "input_tokens": counts_a["input_tokens"],
                                    "component_counts": counts_a,
                                    "menu_mode": request_a.menu_mode,
                                },
                                "system_b": {
                                    "LLM_invoked": decision_b.invoked,
                                    "invocation_reason": decision_b.reason,
                                    "messages": messages_b,
                                    "input_tokens": counts_b["input_tokens"],
                                    "component_counts": counts_b,
                                },
                                "decision_class": outcome_b["classification"],
                                "canonical_intent": outcome_b["canonical_intent"],
                            }

                    history_a.append(
                        {
                            "user": turn["user"],
                            "assistant": str(result_a.get("response") or ""),
                        }
                    )
        finally:
            runtime_a.database.engine.dispose()
            runtime_b.database.engine.dispose()

    results_dir.mkdir(parents=True, exist_ok=True)
    raw_path = results_dir / f"run_{run_id}_raw.csv"
    write_csv(raw_path, raw_rows)
    if run_id == 1:
        write_json(results_dir / "prompt_examples.json", prompt_examples)
    summary = {
        "run_id": run_id,
        "conversations": len(conversations),
        "turns": sum(len(row["turns"]) for row in conversations),
        "rows": len(raw_rows),
        "architectures": dict(totals),
        "pair_outcome_mismatches": sum(
            1
            for row in raw_rows
            if row["architecture"] == "baseline_a"
            and not row["architecture_pair_outcome_match"]
        ),
        "dataset_sha256": sha256_file(dataset_path),
        "reference_sha256": sha256_file(reference_path),
    }
    write_json(results_dir / f"run_{run_id}_summary.json", summary)
    metadata = collect_metadata(
        provider_mode="offline_validated_decision_replay",
        asr_provider="NOT_USED",
        tts_provider="NOT_USED",
        dataset_sha256=sha256_file(dataset_path),
        random_seed=42,
        warmup_count=0,
        measurement_count=len(raw_rows),
        extra={
            "run_id": run_id,
            "experiment": "token_efficiency_v2",
            "tokenizer": tokenizer_metadata(),
            "reference_sha256": sha256_file(reference_path),
            "raw_csv": str(raw_path.relative_to(ROOT)),
            "raw_csv_sha256": sha256_file(raw_path),
            "input_metric": "model-specific estimated input tokens",
            "output_tokens": "NOT_MEASURED",
            "simulated_invocations": True,
            "live_llm_used": False,
            "expected_labels_passed_to_prompt_or_runtime": False,
            "production_behavior_modified": False,
        },
    )
    write_json(results_dir / f"run_{run_id}_metadata.json", metadata)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", type=int, required=True, choices=(1, 2, 3))
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS)
    args = parser.parse_args()
    print(
        json.dumps(
            asyncio.run(
                run_benchmark(
                    run_id=args.run_id,
                    dataset_path=args.dataset,
                    reference_path=args.reference,
                    results_dir=args.results_dir,
                )
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
