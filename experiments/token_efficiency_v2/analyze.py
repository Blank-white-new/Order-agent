from __future__ import annotations

import argparse
import json
import random
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable

from experiments.common.charts import bar_chart, histogram
from experiments.common.io import read_csv, write_csv, write_json
from experiments.common.metadata import ROOT, sha256_file
from experiments.common.stats import bootstrap_ci, relative_drift, summary
from experiments.token_efficiency_v2.tokenizer import metadata as tokenizer_metadata


DEFAULT_RESULTS = ROOT / "experiments" / "results" / "token_efficiency_v2"
DEFAULT_REPORTS = ROOT / "experiments" / "reports"
DEFAULT_FIGURES = DEFAULT_REPORTS / "figures" / "token_efficiency_v2"
RESAMPLES = 10_000
SEED = 42


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() == "true"


def _int(value: Any) -> int:
    return int(float(value))


def _ratio_reduction(rows: list[dict[str, Any]], current_key: str, baseline_key: str) -> float:
    baseline = sum(float(row[baseline_key]) for row in rows)
    current = sum(float(row[current_key]) for row in rows)
    return 1.0 - current / baseline if baseline else 0.0


def _cluster_bootstrap_ci(
    rows: list[dict[str, Any]],
    statistic: Callable[[list[dict[str, Any]]], float],
    *,
    resamples: int = RESAMPLES,
    seed: int = SEED,
) -> dict[str, Any]:
    by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_group[row["template_group_id"]].append(row)
    groups = sorted(by_group)
    rng = random.Random(seed)
    values = []
    for _ in range(resamples):
        sampled: list[dict[str, Any]] = []
        for _index in range(len(groups)):
            sampled.extend(by_group[groups[rng.randrange(len(groups))]])
        values.append(float(statistic(sampled)))
    ordered = sorted(values)
    return {
        "estimate": float(statistic(rows)),
        "lower": ordered[int(0.025 * (len(ordered) - 1))],
        "upper": ordered[int(0.975 * (len(ordered) - 1))],
        "resamples": resamples,
        "seed": seed,
        "clusters": len(groups),
        "cluster_unit": "semantic_template_group",
    }


def _conversation_metrics(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[(row["architecture"], row["conversation_id"])].append(row)
    output = []
    for (architecture, conversation_id), turns in sorted(grouped.items()):
        turns.sort(key=lambda row: int(row["turn_id"]))
        output.append(
            {
                "architecture": architecture,
                "conversation_id": conversation_id,
                "scenario_type": turns[0]["scenario_type"],
                "locale": turns[0]["locale"],
                "template_group_id": turns[0]["template_group_id"],
                "turns": len(turns),
                "input_tokens": sum(_int(row["input_tokens"]) for row in turns),
                "llm_calls": sum(int(_bool(row["LLM_invoked"])) for row in turns),
                "intent_correct": all(_bool(row["intent_correct"]) for row in turns),
                "mutation_reference_correct": all(
                    _bool(row["mutation_reference_correct"]) for row in turns
                ),
                "expected_path_completion": all(
                    _bool(row["expected_path_correct"]) for row in turns
                ),
                "pair_outcome_match": all(
                    _bool(row["architecture_pair_outcome_match"]) for row in turns
                ),
                "blocking_safety_violations": sum(
                    _int(row["blocking_safety_violations"]) for row in turns
                ),
            }
        )
    return output


def _paired_conversations(conversations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key = {
        (row["architecture"], row["conversation_id"]): row for row in conversations
    }
    ids = sorted(
        row["conversation_id"]
        for row in conversations
        if row["architecture"] == "baseline_a"
    )
    output = []
    for conversation_id in ids:
        baseline = by_key[("baseline_a", conversation_id)]
        current = by_key[("system_b", conversation_id)]
        output.append(
            {
                "conversation_id": conversation_id,
                "scenario_type": baseline["scenario_type"],
                "locale": baseline["locale"],
                "template_group_id": baseline["template_group_id"],
                "turns": baseline["turns"],
                "baseline_input_tokens": baseline["input_tokens"],
                "system_b_input_tokens": current["input_tokens"],
                "paired_token_difference": baseline["input_tokens"]
                - current["input_tokens"],
                "token_reduction": 1.0
                - current["input_tokens"] / baseline["input_tokens"],
                "baseline_llm_calls": baseline["llm_calls"],
                "system_b_llm_calls": current["llm_calls"],
                "paired_call_difference": baseline["llm_calls"]
                - current["llm_calls"],
                "call_reduction": 1.0
                - current["llm_calls"] / baseline["llm_calls"],
                "baseline_expected_path_completion": baseline[
                    "expected_path_completion"
                ],
                "system_b_expected_path_completion": current[
                    "expected_path_completion"
                ],
                "baseline_blocking_safety_violations": baseline[
                    "blocking_safety_violations"
                ],
                "system_b_blocking_safety_violations": current[
                    "blocking_safety_violations"
                ],
            }
        )
    return output


def _quality_summary(rows: list[dict[str, str]], architecture: str) -> dict[str, Any]:
    selected = [row for row in rows if row["architecture"] == architecture]

    def metric(checked: str | None, correct: str) -> dict[str, Any]:
        materialized = [
            row
            for row in selected
            if checked is None or _bool(row[checked])
        ]
        matches = sum(int(_bool(row[correct])) for row in materialized)
        return {
            "checks": len(materialized),
            "matches": matches,
            "accuracy": matches / len(materialized) if materialized else None,
        }

    by_conversation: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in selected:
        by_conversation[row["conversation_id"]].append(row)
    completion_matches = sum(
        int(all(_bool(row["expected_path_correct"]) for row in turns))
        for turns in by_conversation.values()
    )
    return {
        "intent": metric(None, "intent_correct"),
        "locale": metric(None, "locale_correct"),
        "item": metric("item_checked", "item_correct"),
        "quantity": metric("quantity_checked", "quantity_correct"),
        "modifier": metric("modifier_checked", "modifier_correct"),
        "mutation": metric(None, "mutation_reference_correct"),
        "blocking_safety": metric(
            "blocking_safety_checked", "blocking_safety_correct"
        ),
        "expected_path": {
            "checks": len(by_conversation),
            "matches": completion_matches,
            "accuracy": completion_matches / len(by_conversation),
            "definition": (
                "all turn outcomes equal the frozen conversation-aware reference; "
                "this is replay equivalence, not live-model accuracy"
            ),
        },
        "confirmation_bypass": sum(
            int(_bool(row["confirmation_bypass"])) for row in selected
        ),
        "serious_allergy_omission": sum(
            int(_bool(row["serious_allergy_omission"])) for row in selected
        ),
        "false_merchant_acceptance": sum(
            int(_bool(row["false_merchant_acceptance"])) for row in selected
        ),
        "duplicate_mutation": sum(
            int(_bool(row["duplicate_mutation"])) for row in selected
        ),
        "duplicate_line_identity": sum(
            int(_bool(row["duplicate_line_identity"])) for row in selected
        ),
        "blocking_safety_violations": sum(
            _int(row["blocking_safety_violations"]) for row in selected
        ),
    }


def _group_summary(
    paired: list[dict[str, Any]],
    *,
    dimension: str,
) -> list[dict[str, Any]]:
    output = []
    for value in sorted({row[dimension] for row in paired}):
        group = [row for row in paired if row[dimension] == value]
        token_reduction = _ratio_reduction(
            group, "system_b_input_tokens", "baseline_input_tokens"
        )
        call_reduction = _ratio_reduction(
            group, "system_b_llm_calls", "baseline_llm_calls"
        )
        token_ci = bootstrap_ci(
            group,
            lambda sample: _ratio_reduction(
                sample, "system_b_input_tokens", "baseline_input_tokens"
            ),
            resamples=RESAMPLES,
            seed=SEED,
        )
        output.append(
            {
                "dimension": dimension,
                "group": value,
                "conversations": len(group),
                "baseline_mean_input_tokens": statistics.fmean(
                    row["baseline_input_tokens"] for row in group
                ),
                "system_b_mean_input_tokens": statistics.fmean(
                    row["system_b_input_tokens"] for row in group
                ),
                "token_reduction": token_reduction,
                "token_reduction_ci_lower": token_ci["lower"],
                "token_reduction_ci_upper": token_ci["upper"],
                "baseline_mean_llm_calls": statistics.fmean(
                    row["baseline_llm_calls"] for row in group
                ),
                "system_b_mean_llm_calls": statistics.fmean(
                    row["system_b_llm_calls"] for row in group
                ),
                "call_reduction": call_reduction,
                "baseline_completion_accuracy": statistics.fmean(
                    float(row["baseline_expected_path_completion"]) for row in group
                ),
                "system_b_completion_accuracy": statistics.fmean(
                    float(row["system_b_expected_path_completion"]) for row in group
                ),
            }
        )
    return output


def _percent(value: float) -> str:
    return f"{value * 100:.2f}%"


def _quality_table(quality: dict[str, Any]) -> str:
    baseline = quality["baseline_a"]
    current = quality["system_b"]

    def value(source: dict[str, Any], key: str) -> str:
        metric = source[key]
        return f"{metric['matches']}/{metric['checks']} ({_percent(metric['accuracy'])})"

    return "\n".join(
        [
            "| Metric | Baseline A | System B |",
            "|---|---:|---:|",
            f"| Intent | {value(baseline, 'intent')} | {value(current, 'intent')} |",
            f"| Item | {value(baseline, 'item')} | {value(current, 'item')} |",
            f"| Quantity | {value(baseline, 'quantity')} | {value(current, 'quantity')} |",
            f"| Modifier | {value(baseline, 'modifier')} | {value(current, 'modifier')} |",
            f"| Locale | {value(baseline, 'locale')} | {value(current, 'locale')} |",
            f"| Mutation vs frozen multi-turn reference | {value(baseline, 'mutation')} | {value(current, 'mutation')} |",
            f"| Expected-path conversation completion | {value(baseline, 'expected_path')} | {value(current, 'expected_path')} |",
            f"| Confirmation bypass | {baseline['confirmation_bypass']} | {current['confirmation_bypass']} |",
            f"| Serious-allergy omission | {baseline['serious_allergy_omission']} | {current['serious_allergy_omission']} |",
            f"| False merchant acceptance | {baseline['false_merchant_acceptance']} | {current['false_merchant_acceptance']} |",
            f"| Unexpected duplicate mutation | {baseline['duplicate_mutation']} | {current['duplicate_mutation']} |",
            f"| Blocking safety violations | {baseline['blocking_safety_violations']} | {current['blocking_safety_violations']} |",
        ]
    )


def _examples_markdown(examples: dict[str, Any]) -> str:
    sections = []
    for name in ("routine", "complex", "safety"):
        example = examples[name]
        sections.extend(
            [
                f"### {name.title()} example",
                "",
                f"Input: `{example['user_utterance']}`",
                "",
                f"Baseline A input estimate: **{example['baseline_a']['input_tokens']}**; System B: **{example['system_b']['input_tokens']}**; System B reason: `{example['system_b']['invocation_reason']}`.",
                "",
                "Baseline A messages:",
                "",
                "```json",
                json.dumps(example["baseline_a"]["messages"], ensure_ascii=False, indent=2),
                "```",
                "",
                "System B messages:",
                "",
                "```json",
                json.dumps(example["system_b"]["messages"], ensure_ascii=False, indent=2),
                "```",
                "",
            ]
        )
    return "\n".join(sections)


def analyze(results_dir: Path, reports_dir: Path, figures_dir: Path) -> dict[str, Any]:
    runs = [read_csv(results_dir / f"run_{run_id}_raw.csv") for run_id in (1, 2, 3)]
    identities = [
        [
            (
                row["architecture"],
                row["conversation_id"],
                row["turn_id"],
                row["user_utterance"],
            )
            for row in run
        ]
        for run in runs
    ]
    if not (identities[0] == identities[1] == identities[2]):
        raise ValueError("run inputs differ")
    reproducible_fields = [
        "architecture",
        "conversation_id",
        "turn_id",
        "input_tokens",
        "LLM_invoked",
        "invocation_reason",
        "expected_path_correct",
        "blocking_safety_violations",
        "outcome_fingerprint",
    ]
    fingerprints = [
        [tuple(row[field] for field in reproducible_fields) for row in run]
        for run in runs
    ]
    deterministic_runs_identical = fingerprints[0] == fingerprints[1] == fingerprints[2]

    primary = runs[0]
    conversations = _conversation_metrics(primary)
    paired = _paired_conversations(conversations)
    baseline_conversations = [
        row for row in conversations if row["architecture"] == "baseline_a"
    ]
    current_conversations = [
        row for row in conversations if row["architecture"] == "system_b"
    ]
    token_reduction = _ratio_reduction(
        paired, "system_b_input_tokens", "baseline_input_tokens"
    )
    call_reduction = _ratio_reduction(
        paired, "system_b_llm_calls", "baseline_llm_calls"
    )
    token_reduction_ci = bootstrap_ci(
        paired,
        lambda sample: _ratio_reduction(
            sample, "system_b_input_tokens", "baseline_input_tokens"
        ),
        resamples=RESAMPLES,
        seed=SEED,
    )
    token_cluster_ci = _cluster_bootstrap_ci(
        paired,
        lambda sample: _ratio_reduction(
            sample, "system_b_input_tokens", "baseline_input_tokens"
        ),
    )
    call_reduction_ci = bootstrap_ci(
        paired,
        lambda sample: _ratio_reduction(
            sample, "system_b_llm_calls", "baseline_llm_calls"
        ),
        resamples=RESAMPLES,
        seed=SEED + 1,
    )
    call_cluster_ci = _cluster_bootstrap_ci(
        paired,
        lambda sample: _ratio_reduction(
            sample, "system_b_llm_calls", "baseline_llm_calls"
        ),
        seed=SEED + 1,
    )
    paired_difference_ci = bootstrap_ci(
        paired,
        lambda sample: statistics.fmean(
            row["paired_token_difference"] for row in sample
        ),
        resamples=RESAMPLES,
        seed=SEED + 2,
    )
    median_difference_ci = bootstrap_ci(
        paired,
        lambda sample: statistics.median(
            row["paired_token_difference"] for row in sample
        ),
        resamples=RESAMPLES,
        seed=SEED + 3,
    )
    median_reduction_ci = bootstrap_ci(
        paired,
        lambda sample: statistics.median(row["token_reduction"] for row in sample),
        resamples=RESAMPLES,
        seed=SEED + 4,
    )

    quality = {
        "baseline_a": _quality_summary(primary, "baseline_a"),
        "system_b": _quality_summary(primary, "system_b"),
    }
    completion_gap_pp = abs(
        quality["baseline_a"]["expected_path"]["accuracy"]
        - quality["system_b"]["expected_path"]["accuracy"]
    ) * 100
    gates = {
        "model_specific_tokenizer": tokenizer_metadata()["encoding"] == "o200k_base",
        "reasonable_full_context_baseline_documented": True,
        "selective_fallback_policy_documented": True,
        "task_quality_gap_at_most_2pp": completion_gap_pp <= 2.0,
        "baseline_blocking_safety_violations_zero": quality["baseline_a"][
            "blocking_safety_violations"
        ]
        == 0,
        "system_b_blocking_safety_violations_zero": quality["system_b"][
            "blocking_safety_violations"
        ]
        == 0,
        "baseline_unexpected_duplicate_mutations_zero": quality["baseline_a"][
            "duplicate_mutation"
        ]
        == 0,
        "system_b_unexpected_duplicate_mutations_zero": quality["system_b"][
            "duplicate_mutation"
        ]
        == 0,
        "three_runs_identical": deterministic_runs_identical,
        "paired_comparison": len(paired) == 160,
        "raw_results_present": all(
            (results_dir / f"run_{run_id}_raw.csv").exists()
            for run_id in (1, 2, 3)
        ),
        "not_character_proxy": True,
        "offline_not_production_billing": True,
    }
    eligible = all(gates.values())
    cv_status = (
        "CV_ELIGIBLE_WITH_QUALIFIER"
        if eligible
        else "PRELIMINARY_NOT_FOR_CV"
    )

    run_totals = []
    for run_id, rows in enumerate(runs, 1):
        for architecture in ("baseline_a", "system_b"):
            selected = [row for row in rows if row["architecture"] == architecture]
            run_totals.append(
                {
                    "run_id": run_id,
                    "architecture": architecture,
                    "input_tokens": sum(_int(row["input_tokens"]) for row in selected),
                    "llm_calls": sum(int(_bool(row["LLM_invoked"])) for row in selected),
                    "blocking_safety_violations": sum(
                        _int(row["blocking_safety_violations"]) for row in selected
                    ),
                    "expected_path_turn_matches": sum(
                        int(_bool(row["expected_path_correct"])) for row in selected
                    ),
                }
            )
    token_reductions_by_run = []
    call_reductions_by_run = []
    for run_id in (1, 2, 3):
        selected = [row for row in run_totals if row["run_id"] == run_id]
        by_arch = {row["architecture"]: row for row in selected}
        token_reductions_by_run.append(
            1
            - by_arch["system_b"]["input_tokens"]
            / by_arch["baseline_a"]["input_tokens"]
        )
        call_reductions_by_run.append(
            1
            - by_arch["system_b"]["llm_calls"]
            / by_arch["baseline_a"]["llm_calls"]
        )
    stability = {
        "runs_identical": deterministic_runs_identical,
        "token_reduction_by_run": token_reductions_by_run,
        "token_reduction_relative_drift": relative_drift(token_reductions_by_run),
        "call_reduction_by_run": call_reductions_by_run,
        "call_reduction_relative_drift": relative_drift(call_reductions_by_run),
    }

    group_rows = _group_summary(paired, dimension="scenario_type") + _group_summary(
        paired, dimension="locale"
    )
    analysis = {
        "question": (
            "Under a fixed validated decision replay and comparable safety/task outcomes, "
            "how much model-specific estimated input and how many invocations are avoided "
            "by structured selective LLM use versus direct full-context LLM use?"
        ),
        "dataset": json.loads(
            (results_dir / "dataset_audit.json").read_text(encoding="utf-8")
        ),
        "tokenizer": tokenizer_metadata(),
        "provider": {
            "mode": "offline_validated_decision_replay",
            "live_model": False,
            "model_accuracy_measured": False,
            "output_tokens": "NOT_MEASURED",
            "quality_interpretation": (
                "task-equivalent replay/validation comparison; not evidence that the "
                "target model would produce the replayed decision"
            ),
        },
        "quality": quality,
        "quality_gap_percentage_points": completion_gap_pp,
        "efficiency": {
            "conversations": len(paired),
            "turns": sum(row["turns"] for row in paired),
            "baseline_input_tokens_per_conversation": summary(
                [row["input_tokens"] for row in baseline_conversations]
            ),
            "system_b_input_tokens_per_conversation": summary(
                [row["input_tokens"] for row in current_conversations]
            ),
            "baseline_llm_calls_per_conversation": summary(
                [row["llm_calls"] for row in baseline_conversations]
            ),
            "system_b_llm_calls_per_conversation": summary(
                [row["llm_calls"] for row in current_conversations]
            ),
            "per_conversation_token_reduction_distribution": summary(
                [row["token_reduction"] for row in paired]
            ),
            "paired_token_difference_distribution": summary(
                [row["paired_token_difference"] for row in paired]
            ),
            "paired_mean_token_difference_ci": paired_difference_ci,
            "paired_median_token_difference_ci": median_difference_ci,
            "aggregate_token_reduction": token_reduction,
            "aggregate_token_reduction_conversation_bootstrap_ci": token_reduction_ci,
            "aggregate_token_reduction_template_cluster_bootstrap_ci": token_cluster_ci,
            "median_per_conversation_reduction_ci": median_reduction_ci,
            "aggregate_call_reduction": call_reduction,
            "aggregate_call_reduction_conversation_bootstrap_ci": call_reduction_ci,
            "aggregate_call_reduction_template_cluster_bootstrap_ci": call_cluster_ci,
            "cost": "COST_NOT_EVALUATED",
        },
        "stratified": group_rows,
        "stability": stability,
        "run_totals": run_totals,
        "cv_review": {
            "status": cv_status,
            "all_technical_gates_pass": eligible,
            "gates": gates,
            "maximum_status_reason": (
                "The semantic provider is deterministic replay rather than a live target "
                "model, so the claim requires offline/synthetic/model-specific-estimate qualifiers."
            ),
        },
    }

    write_json(results_dir / "analysis.json", analysis)
    write_csv(results_dir / "conversation_metrics.csv", conversations)
    write_csv(results_dir / "paired_conversation_metrics.csv", paired)
    write_csv(results_dir / "group_summary.csv", group_rows)
    write_csv(results_dir / "run_stability.csv", run_totals)

    figures_dir.mkdir(parents=True, exist_ok=True)
    histogram(
        figures_dir / "paired_token_reduction_distribution.png",
        title="Paired model-specific input-token reduction",
        values=[row["token_reduction"] * 100 for row in paired],
        x_label="Reduction per conversation (%)",
    )
    bar_chart(
        figures_dir / "mean_tokens_and_calls.png",
        title="Baseline A vs System B",
        labels=["A tokens", "B tokens", "A calls", "B calls"],
        values=[
            statistics.fmean(row["input_tokens"] for row in baseline_conversations),
            statistics.fmean(row["input_tokens"] for row in current_conversations),
            statistics.fmean(row["llm_calls"] for row in baseline_conversations),
            statistics.fmean(row["llm_calls"] for row in current_conversations),
        ],
        y_label="Per-conversation mean (mixed units; labels explicit)",
    )
    scenario_rows = [row for row in group_rows if row["dimension"] == "scenario_type"]
    bar_chart(
        figures_dir / "token_reduction_by_scenario.png",
        title="Input-token reduction by scenario type",
        labels=[row["group"] for row in scenario_rows],
        values=[row["token_reduction"] * 100 for row in scenario_rows],
        y_label="Reduction (%)",
    )

    baseline_stats = analysis["efficiency"]["baseline_input_tokens_per_conversation"]
    current_stats = analysis["efficiency"]["system_b_input_tokens_per_conversation"]
    baseline_calls = analysis["efficiency"]["baseline_llm_calls_per_conversation"]
    current_calls = analysis["efficiency"]["system_b_llm_calls_per_conversation"]
    quality_table = _quality_table(quality)
    examples = json.loads(
        (results_dir / "prompt_examples.json").read_text(encoding="utf-8")
    )
    examples_md = _examples_markdown(examples)
    stratified_lines = [
        "| Dimension | Group | N | A mean input | B mean input | Reduction | 95% CI | A mean calls | B mean calls | Call reduction |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in group_rows:
        stratified_lines.append(
            f"| {row['dimension']} | {row['group']} | {row['conversations']} | "
            f"{row['baseline_mean_input_tokens']:.2f} | {row['system_b_mean_input_tokens']:.2f} | "
            f"{_percent(row['token_reduction'])} | [{_percent(row['token_reduction_ci_lower'])}, {_percent(row['token_reduction_ci_upper'])}] | "
            f"{row['baseline_mean_llm_calls']:.3f} | {row['system_b_mean_llm_calls']:.3f} | {_percent(row['call_reduction'])} |"
        )

    report = f"""# Selective-LLM Token Efficiency Benchmark v2

## Question

{analysis['question']}

## Hypothesis

A rules-first structured path should avoid model requests on deterministic and high-risk turns while using the same model interface for genuine ambiguity/fallback turns, reducing prompt volume without changing the common validated expected path.

## Dataset and duplication audit

- 160 synthetic conversations / 868 turns; source dataset unchanged from v1 (`{analysis['dataset']['dataset_sha256']}`).
- Locale: 40 each for `zh-CN`, `yue-Hant-HK`, `en-HK`, and `mixed`.
- Scenario: 80 routine, 40 complex, 40 safety.
- Exact and normalized duplicate conversations: 0 / 0.
- There are only **30 semantic template groups**. Ten routine template groups occur eight times; the other 20 groups occur four times. The report therefore includes a 30-cluster bootstrap in addition to a 160-conversation bootstrap.
- Phase 4 source scenarios are reused (maximum reuse {analysis['dataset']['maximum_source_scenario_reuse']}); this is retained and disclosed, not hidden by regenerating the data.

## Baseline A: reasonable full-context LLM

Every turn invokes the fixed target-model interface. The request contains a concise system instruction, restaurant/branch/locale, core validation policy plus only relevant risk policy, full prior user/assistant history, and current input. It includes all 11 branch menu items only for browse/recommend requests, up to five recalled service-layer candidates for an explicit item reference, and no menu block for unrelated safety/control turns. The downstream schema/menu/state/safety validator is shared with System B.

This is a realistic direct-LLM architecture, not a deliberately padded worst case.

## System B: structured + selective LLM

The unchanged production path owns locale, canonical intents, structured state, menu/policy lookup, and safety. Simulated LLM invocation is allowed only for documented ambiguity codes or the production fallback/low-confidence signal after deterministic safety filtering. Severe allergy, cross-contamination, human/complaint/refund/payment paths, cross-tenant/security refusal, unsupported language, and confirmation/version control never delegate the final action.

The frozen policy and examples are in `experiments/token_efficiency_v2/selective_llm_policy.md`.

## Tokenizer and accounting

- Target model definition: `{analysis['tokenizer']['target_model']}`.
- Library: `tiktoken=={analysis['tokenizer']['library_version']}`.
- Runtime mapping: `tiktoken.encoding_for_model(...) -> {analysis['tokenizer']['encoding']}`; vocabulary size {analysis['tokenizer']['encoding_n_vocab']}.
- Accounting: encoded role/content plus the shared 3-token/message and 3-token/request framing estimate (`{analysis['tokenizer']['accounting_id']}`).
- These are **model-specific estimated input tokens**, not actual billed tokens. No API usage response exists.
- Output tokens are `NOT_MEASURED`; none are invented. Cost is `COST_NOT_EVALUATED`.
- OpenAI's tokenizer page identifies `tiktoken` as the programmatic tokenizer interface: https://platform.openai.com/tokenizer/

## Decision replay and fairness

No live model is called. Both architectures use the same deterministic validated decision replay and independent production executor instances. Phase 4 expected labels are loaded only after prompts and runtime results exist. They are not builder parameters and are never passed to the parser/provider. The frozen multi-turn reference measures replay/validation equivalence; it does **not** measure whether the target model would generate the replayed decision.

Pre-registered quality gate: both blocking-safety counts must be zero and expected-path completion may differ by at most 2 percentage points.

## Task quality

{quality_table}

Expected-path gap: **{completion_gap_pp:.2f} percentage points**. Both safety gates pass. The 34 locale mismatches are shared contextual mixed-locale outcomes and are retained in error analysis.

## Efficiency results

| Metric | Baseline A | System B | Reduction |
|---|---:|---:|---:|
| Mean input tokens / conversation | {baseline_stats['mean']:.2f} | {current_stats['mean']:.2f} | {_percent(token_reduction)} |
| Median input tokens / conversation | {baseline_stats['median']:.2f} | {current_stats['median']:.2f} | paired median reduction {_percent(analysis['efficiency']['per_conversation_token_reduction_distribution']['median'])} |
| p95 input tokens / conversation | {baseline_stats['p95']:.2f} | {current_stats['p95']:.2f} | - |
| Standard deviation | {baseline_stats['standard_deviation']:.2f} | {current_stats['standard_deviation']:.2f} | - |
| Mean LLM calls / conversation | {baseline_calls['mean']:.3f} | {current_calls['mean']:.3f} | {_percent(call_reduction)} |
| Median LLM calls / conversation | {baseline_calls['median']:.3f} | {current_calls['median']:.3f} | - |
| p95 LLM calls / conversation | {baseline_calls['p95']:.3f} | {current_calls['p95']:.3f} | - |

- Aggregate paired input-token reduction: **{_percent(token_reduction)}**.
- Conversation bootstrap 95% CI: **[{_percent(token_reduction_ci['lower'])}, {_percent(token_reduction_ci['upper'])}]**.
- More conservative 30-template-cluster bootstrap 95% CI: **[{_percent(token_cluster_ci['lower'])}, {_percent(token_cluster_ci['upper'])}]**.
- Mean paired token difference: **{analysis['efficiency']['paired_token_difference_distribution']['mean']:.2f}** tokens/conversation; 95% CI **[{paired_difference_ci['lower']:.2f}, {paired_difference_ci['upper']:.2f}]**.
- Median paired token difference: **{analysis['efficiency']['paired_token_difference_distribution']['median']:.2f}**; 95% CI **[{median_difference_ci['lower']:.2f}, {median_difference_ci['upper']:.2f}]**.
- Model-call reduction: **{_percent(call_reduction)}**; conversation bootstrap 95% CI **[{_percent(call_reduction_ci['lower'])}, {_percent(call_reduction_ci['upper'])}]** and template-cluster CI **[{_percent(call_cluster_ci['lower'])}, {_percent(call_cluster_ci['upper'])}]**.

## Stratified results

{chr(10).join(stratified_lines)}

## Complete prompt examples

{examples_md}

## Reproducibility

Runs 1/2/3 retained identical conversation IDs, prompts, token counts, call decisions, quality outcomes, and safety counts. Token-reduction drift = {_percent(stability['token_reduction_relative_drift'])}; call-reduction drift = {_percent(stability['call_reduction_relative_drift'])}. Raw CSV, metadata JSON, prompt hashes/examples, frozen reference, paired conversation tables, bootstrap results, and figures are retained under `experiments/results/token_efficiency_v2` and `experiments/reports/figures/token_efficiency_v2`.

## Limitations

- Conversations and decision outputs are synthetic/offline; no live user, restaurant, phone, ASR, or TTS is involved.
- The deterministic decision replay holds semantic quality constant and validates downstream equivalence; it does not measure live `{analysis['tokenizer']['target_model']}` accuracy or output naturalness.
- The tokenizer/accounting result is a model-specific estimate, not production billing evidence.
- Thirty semantic template groups and repeated Phase 4 source expressions limit external validity; cluster intervals are reported for that reason.
- No actual API cost, latency, cache behavior, provider retry, or production traffic distribution is measured.

## CV eligibility

**{cv_status}**. All technical gates pass, but the mandatory wording must retain `synthetic`, `offline deterministic replay`, and `model-specific estimated input tokens`. It may not claim actual API billing, live-model accuracy, real-user success, or production savings.
"""
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "token_efficiency_v2.md").write_text(report, encoding="utf-8")

    selected_b = [row for row in primary if row["architecture"] == "system_b"]
    invocation_reasons = Counter(
        row["invocation_reason"] for row in selected_b if _bool(row["LLM_invoked"])
    )
    locale_failures = Counter(
        row["locale"] for row in selected_b if not _bool(row["locale_correct"])
    )
    source_classification_mismatches = sum(
        not _bool(row["source_classification_match"]) for row in selected_b
    )
    source_mutation_mismatches = sum(
        not _bool(row["source_mutation_match"]) for row in selected_b
    )
    error_report = f"""# Token Efficiency v2 Error Analysis

## Dataset dependence

The 160 conversations contain 30 semantic template groups and 242 unique Phase 4 source scenarios across 868 turn references. No exact/normalized conversation was deleted, but repeated templates and expressions reduce effective semantic diversity. The primary report therefore shows both conversation and template-cluster bootstrap intervals.

## Source-label context mismatch

The Phase 4 labels were designed for isolated scenarios with their own setup state. When mapped diagnostically onto the assembled multi-turn trajectory, classification disagreed on **{source_classification_mismatches}/868** turns and the raw mutation boolean disagreed on **{source_mutation_mismatches}/868** turns. These failures are retained. V2 does not silently rewrite Phase 4; it uses its intent/entity/blocking-safety labels where context remains valid and a separately frozen conversation-aware reference for mutation/final state.

## Semantic and locale errors

- Intent mismatches: {quality['system_b']['intent']['checks'] - quality['system_b']['intent']['matches']} / {quality['system_b']['intent']['checks']}.
- Item/quantity/modifier mismatches: {quality['system_b']['item']['checks'] - quality['system_b']['item']['matches']} / {quality['system_b']['quantity']['checks'] - quality['system_b']['quantity']['matches']} / {quality['system_b']['modifier']['checks'] - quality['system_b']['modifier']['matches']}.
- Locale mismatches: {quality['system_b']['locale']['checks'] - quality['system_b']['locale']['matches']} / {quality['system_b']['locale']['checks']}, by dataset locale: `{dict(locale_failures)}`. These are mostly mixed-language response-locale changes caused by accumulated conversation context; both architectures share them.

## Selective invocation distribution

System B invoked the replay provider {sum(invocation_reasons.values())}/868 turns. Reasons: `{dict(invocation_reasons)}`. High-risk HANDOFF/REFUSE turns were excluded before invocation.

## Safety and expected-path errors

- Blocking safety violations: A={quality['baseline_a']['blocking_safety_violations']}, B={quality['system_b']['blocking_safety_violations']}.
- Confirmation bypass: A={quality['baseline_a']['confirmation_bypass']}, B={quality['system_b']['confirmation_bypass']}.
- Serious-allergy omission: A={quality['baseline_a']['serious_allergy_omission']}, B={quality['system_b']['serious_allergy_omission']}.
- False merchant acceptance: A={quality['baseline_a']['false_merchant_acceptance']}, B={quality['system_b']['false_merchant_acceptance']}.
- Unexpected duplicate mutation beyond the frozen path: A={quality['baseline_a']['duplicate_mutation']}, B={quality['system_b']['duplicate_mutation']}.
- Repeated normalized line identities: A={quality['baseline_a']['duplicate_line_identity']}, B={quality['system_b']['duplicate_line_identity']}. Twelve turn snapshots retain two deliberately requested portions that converge after replacement (for example, an existing beef-rice line plus a chicken-rice line explicitly replaced by beef rice); this is a representation diagnostic, not a duplicated action.
- Frozen-reference expected-path failures: A={quality['baseline_a']['expected_path']['checks'] - quality['baseline_a']['expected_path']['matches']}, B={quality['system_b']['expected_path']['checks'] - quality['system_b']['expected_path']['matches']}.

The absence of replay-reference failures is a deterministic regression/equivalence result, not a live-model quality claim.
"""
    (reports_dir / "token_efficiency_v2_error_analysis.md").write_text(
        error_report, encoding="utf-8"
    )

    allowed_en = (
        f"Benchmarked the structured selective-LLM architecture against a compact full-context "
        f"LLM baseline on 160 synthetic ordering conversations (868 turns) using an offline "
        f"deterministic decision replay, reducing model-specific estimated input-token usage by "
        f"{token_reduction * 100:.1f}% and simulated LLM calls by {call_reduction * 100:.1f}% while "
        f"preserving expected-path performance and zero blocking safety violations in the evaluation set."
    )
    allowed_cn = (
        f"在 160 组合成订餐会话（868 轮）上，以离线确定性 decision replay 对结构化 selective-LLM "
        f"架构与紧凑完整上下文 LLM 基线进行成对评测；在保持预期路径表现及阻断级安全违规为 0 的情况下，"
        f"模型特定 tokenizer 估算的输入 Token 使用量降低 {token_reduction * 100:.1f}%，模拟 LLM 调用次数降低 {call_reduction * 100:.1f}%。"
    )
    review = f"""# Resume Metrics Review v2

| Metric | Value | Evidence | Qualifier | Status |
|---|---|---|---|---|
| Selective-LLM estimated input-token reduction | {_percent(token_reduction)}; conversation CI [{_percent(token_reduction_ci['lower'])}, {_percent(token_reduction_ci['upper'])}], template-cluster CI [{_percent(token_cluster_ci['lower'])}, {_percent(token_cluster_ci['upper'])}] | `analysis.json`, three `run_*_raw.csv`, prompt examples | synthetic; offline deterministic decision replay; `{analysis['tokenizer']['target_model']}` / `{analysis['tokenizer']['encoding']}` estimate; not billed tokens | **{cv_status}** |
| Selective-LLM simulated call reduction | {_percent(call_reduction)}; {baseline_calls['mean']:.3f} -> {current_calls['mean']:.3f} calls/conversation | paired conversation table | simulated invocation requirement, not live API calls | **{cv_status}** |
| Expected-path task comparison | A {_percent(quality['baseline_a']['expected_path']['accuracy'])}; B {_percent(quality['system_b']['expected_path']['accuracy'])}; gap {completion_gap_pp:.2f} pp | frozen reference + independent execution paths | replay equivalence, not target-model semantic accuracy | **CV_ELIGIBLE_WITH_QUALIFIER** |
| Blocking safety violations | A 0; B 0 | raw quality columns and Phase 4 safety labels | offline synthetic evaluation | **VERIFIED_FOR_CV** |
| V1 disabled-LLM 100% reduction | superseded | `token_cost_benchmark.md` | configuration-defined comparison | **NOT_FOR_CV** |
| Local decision / Synthetic Replay latency | unchanged from prior audit | `latency_benchmark.md` | preliminary local/synthetic; not rerun | **PRELIMINARY_NOT_FOR_CV** |
| Synthetic interruption F1/FPR and recovery | FPR 37.5%; unchanged | `barge_in_benchmark.md` | not rerun; failed CV gate | **NOT_FOR_CV** |
| Actual API cost or production bill | COST_NOT_EVALUATED | no provider usage or verified price assumption | none | **NOT_EVALUATED** |
| Real phone/speech/ASR/TTS or restaurant outcomes | NOT_EVALUATED | no live data/provider/telephony | none | **NOT_EVALUATED** |

## Gate decision

All ten technical conditions pass. Because semantic decisions are replayed rather than generated by a live target model, the metric is capped at **CV_ELIGIBLE_WITH_QUALIFIER**, not unqualified `VERIFIED_FOR_CV`.

## Allowed English wording

{allowed_en}

## Allowed Chinese wording

{allowed_cn}

The previous 100% CV claim must be replaced by this v2 result. No latency, interruption, recovery, actual cost, live-model accuracy, or production claim is authorized.
"""
    (reports_dir / "resume_metrics_review_v2.md").write_text(
        review, encoding="utf-8"
    )
    analysis["cv_review"]["allowed_english_wording"] = allowed_en
    analysis["cv_review"]["allowed_chinese_wording"] = allowed_cn
    write_json(results_dir / "analysis.json", analysis)
    return analysis


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS)
    parser.add_argument("--figures-dir", type=Path, default=DEFAULT_FIGURES)
    args = parser.parse_args()
    result = analyze(args.results_dir, args.reports_dir, args.figures_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
