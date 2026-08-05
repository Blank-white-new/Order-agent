from __future__ import annotations

import inspect
import json

from experiments.token_efficiency_v2.audit_dataset import audit_dataset
from experiments.common.io import read_csv
from experiments.common.metadata import ROOT
from experiments.token_efficiency_v2.baseline import build_baseline_request
from experiments.token_efficiency_v2.quality_eval import (
    DecisionReplayProvider,
    has_unexpected_duplicate_mutation,
)
from experiments.token_efficiency_v2.selective_llm import decide_selective_invocation
from experiments.token_efficiency_v2.tokenizer import (
    ENCODING_NAME,
    MODEL_ID,
    TIKTOKEN_VERSION,
    count_messages,
    count_text,
    metadata,
)


MENU = [
    {
        "id": "cola",
        "name": "Cola",
        "aliases": ["可乐", "可樂"],
        "category": "Drinks",
        "base_price_minor": 600,
        "currency": "HKD",
        "available": True,
        "options": ["No ice"],
        "allergens": [],
    },
    {
        "id": "chicken_leg_rice",
        "name": "Chicken leg rice",
        "aliases": ["鸡腿饭", "雞髀飯"],
        "category": "Rice",
        "base_price_minor": 2600,
        "currency": "HKD",
        "available": True,
        "options": ["Extra rice"],
        "allergens": [],
    },
]


def _request(text: str, *, history=None):
    return build_baseline_request(
        user_utterance=text,
        history=history or [],
        restaurant_code="restaurant-a",
        branch_code="central",
        locale="zh-CN",
        menu_items=MENU,
        candidate_items=MENU,
    )


def test_model_specific_tokenizer_is_pinned_and_reproducible() -> None:
    info = metadata()
    assert info["target_model"] == MODEL_ID == "gpt-4o-mini-2024-07-18"
    assert info["encoding"] == ENCODING_NAME == "o200k_base"
    assert info["library_version"] == TIKTOKEN_VERSION == "0.13.0"
    assert info["actual_billing_count"] is False
    assert count_text("再加一份可乐 / add one more cola") == 11
    assert count_text("再加一份可乐 / add one more cola") == 11


def test_shared_message_accounting_is_deterministic() -> None:
    messages = [{"role": "system", "content": "safe"}, {"role": "user", "content": "菜单"}]
    first = count_messages(messages)
    second = count_messages(messages)
    assert first == second
    assert first.total == first.content + first.framing
    assert first.message_count == 2


def test_reasonable_baseline_uses_history_and_relevant_context() -> None:
    routine = _request("再加一份可乐")
    unrelated = _request("我有严重花生过敏")
    with_history = _request(
        "再加一份可乐",
        history=[{"user": "show the menu", "assistant": "Here is the menu."}],
    )
    assert routine.menu_mode == "relevant_item_candidates"
    assert unrelated.menu_mode == "not_required"
    assert len(with_history.messages) == len(routine.messages) + 2
    assert count_messages(with_history.messages).total > count_messages(routine.messages).total


def test_expected_labels_are_not_prompt_builder_inputs() -> None:
    signature = inspect.signature(build_baseline_request)
    forbidden = {"expected_intent", "expected_classification", "scenario_type", "source_scenario_id"}
    assert forbidden.isdisjoint(signature.parameters)
    serialized = str(_request("show the menu").messages)
    assert "expected_" not in serialized
    assert "P4-" not in serialized


def test_selective_policy_invokes_only_safe_ambiguity_or_real_fallback() -> None:
    ambiguous = {
        "trace": {
            "multilingual": {"canonicalIntent": "ADD_ITEM", "ambiguities": ["AMBIGUOUS_ITEM"]},
            "safety": {"classification": "CONFIRM"},
        }
    }
    safety = {
        "trace": {
            "multilingual": {"canonicalIntent": "UNKNOWN", "ambiguities": []},
            "safety": {"classification": "HANDOFF"},
            "llmFallbackReason": "unknown",
        }
    }
    fallback = {
        "trace": {
            "multilingual": {"canonicalIntent": "START_NEW_ORDER", "ambiguities": []},
            "safety": {"classification": "AUTO_DRAFT"},
            "llmFallbackReason": "fallback",
        }
    }
    assert decide_selective_invocation(ambiguous).invoked is True
    assert decide_selective_invocation(safety).invoked is False
    assert decide_selective_invocation(fallback).invoked is True


def test_dataset_audit_retains_template_dependence() -> None:
    audit, manifest = audit_dataset()
    assert audit["conversations"] == 160
    assert audit["turns"] == 868
    assert audit["exact_duplicate_conversations"] == 0
    assert audit["normalized_duplicate_conversations"] == 0
    assert audit["semantic_template_groups"] == 30
    assert audit["dataset_changed_for_v2"] is False
    assert len({row["template_group_id"] for row in manifest}) == 30


def test_replay_provider_does_not_accept_expected_labels() -> None:
    reference = {("TOK-01-001", 1): {"canonical_intent": "MENU_QUERY"}}
    provider = DecisionReplayProvider(reference)
    signature = inspect.signature(provider.invoke)
    assert "expected_intent" not in signature.parameters
    first = provider.invoke(
        conversation_id="TOK-01-001", turn_id=1, prompt_sha256="a" * 64
    )
    first["canonical_intent"] = "CHANGED"
    second = provider.invoke(
        conversation_id="TOK-01-001", turn_id=1, prompt_sha256="b" * 64
    )
    assert second["canonical_intent"] == "MENU_QUERY"


def test_duplicate_mutation_distinguishes_requested_repeated_lines() -> None:
    line = {
        "item_id": "beef_rice",
        "options": [],
        "spicy_level": None,
        "exclusions": [],
        "notes": None,
    }
    assert has_unexpected_duplicate_mutation([line, line], [line, line]) is False
    assert has_unexpected_duplicate_mutation([line, line], [line]) is True


def test_three_v2_runs_are_identical_and_keep_all_rows() -> None:
    results = ROOT / "experiments" / "results" / "token_efficiency_v2"
    runs = [read_csv(results / f"run_{run_id}_raw.csv") for run_id in (1, 2, 3)]
    assert all(len(run) == 1736 for run in runs)
    fields = (
        "architecture",
        "conversation_id",
        "turn_id",
        "input_tokens",
        "LLM_invoked",
        "invocation_reason",
        "expected_path_correct",
        "outcome_fingerprint",
    )
    fingerprints = [[tuple(row[field] for field in fields) for row in run] for run in runs]
    assert fingerprints[0] == fingerprints[1] == fingerprints[2]
    assert all(row["output_tokens"] == "0" for run in runs for row in run)
    assert all(row["output_token_status"] == "NOT_MEASURED" for run in runs for row in run)


def test_v2_invocation_and_quality_gates_match_policy() -> None:
    results = ROOT / "experiments" / "results" / "token_efficiency_v2"
    rows = read_csv(results / "run_1_raw.csv")
    baseline = [row for row in rows if row["architecture"] == "baseline_a"]
    current = [row for row in rows if row["architecture"] == "system_b"]
    assert len(baseline) == len(current) == 868
    assert all(row["LLM_invoked"] == "True" for row in baseline)
    assert sum(row["LLM_invoked"] == "True" for row in current) == 52
    assert all(
        row["LLM_invoked"] == "False"
        for row in current
        if row["decision_class"] in {"HANDOFF", "REFUSE"}
    )
    assert sum(int(row["blocking_safety_violations"]) for row in rows) == 0
    assert sum(row["duplicate_mutation"] == "True" for row in rows) == 0
    assert all(row["expected_path_correct"] == "True" for row in rows)


def test_v2_analysis_is_qualified_not_unqualified_billing_claim() -> None:
    results = ROOT / "experiments" / "results" / "token_efficiency_v2"
    analysis = json.loads((results / "analysis.json").read_text(encoding="utf-8"))
    assert analysis["cv_review"]["status"] == "CV_ELIGIBLE_WITH_QUALIFIER"
    assert analysis["cv_review"]["all_technical_gates_pass"] is True
    assert analysis["tokenizer"]["actual_billing_count"] is False
    assert analysis["provider"]["live_model"] is False
    assert analysis["provider"]["model_accuracy_measured"] is False
    assert analysis["efficiency"]["cost"] == "COST_NOT_EVALUATED"
    examples = (results / "prompt_examples.json").read_text(encoding="utf-8")
    assert "expected_intent" not in examples
    assert "expected_classification" not in examples
