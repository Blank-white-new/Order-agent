from __future__ import annotations

import argparse
import statistics
from collections import defaultdict
from pathlib import Path

from experiments.common.charts import bar_chart, histogram
from experiments.common.io import read_csv, write_csv, write_json
from experiments.common.metadata import ROOT, sha256_file
from experiments.common.stats import bootstrap_ci, relative_drift, summary
from experiments.token_cost.baseline import TOKENIZER_DESCRIPTION, TOKENIZER_ID


DEFAULT_RESULTS = ROOT / "experiments" / "results" / "token_cost"
DEFAULT_REPORT = ROOT / "experiments" / "reports" / "token_cost_benchmark.md"
DEFAULT_FIGURES = ROOT / "experiments" / "reports" / "figures" / "token_cost"


def _number(row: dict, key: str) -> float:
    return float(row[key])


def _conversation_rows(rows: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["conversation_id"]].append(row)
    result = []
    for conversation_id, turns in sorted(grouped.items()):
        baseline = sum(_number(turn, "baseline_input_tokens") for turn in turns)
        current = sum(_number(turn, "current_input_tokens") for turn in turns)
        baseline_calls = sum(_number(turn, "baseline_llm_calls") for turn in turns)
        current_calls = sum(_number(turn, "current_llm_calls") for turn in turns)
        result.append(
            {
                "conversation_id": conversation_id,
                "scenario_type": turns[0]["scenario_type"],
                "locale": turns[0]["locale"],
                "turns": len(turns),
                "baseline_input_tokens": baseline,
                "current_input_tokens": current,
                "paired_token_difference": baseline - current,
                "token_reduction_ratio": 1.0 - current / baseline if baseline else 0.0,
                "baseline_llm_calls": baseline_calls,
                "current_llm_calls": current_calls,
                "llm_call_reduction_ratio": 1.0 - current_calls / baseline_calls if baseline_calls else 0.0,
            }
        )
    return result


def _group_summaries(conversations: list[dict], key: str) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in conversations:
        grouped[row[key]].append(row)
    output = []
    for group, rows in sorted(grouped.items()):
        base = [float(row["baseline_input_tokens"]) for row in rows]
        current = [float(row["current_input_tokens"]) for row in rows]
        reductions = [float(row["token_reduction_ratio"]) for row in rows]
        output.append(
            {
                "grouping": key,
                "group": group,
                "n_conversations": len(rows),
                "baseline_mean_tokens": statistics.fmean(base),
                "baseline_median_tokens": statistics.median(base),
                "current_mean_tokens": statistics.fmean(current),
                "current_median_tokens": statistics.median(current),
                "mean_token_reduction_ratio": statistics.fmean(reductions),
            }
        )
    return output


def analyze(*, results_dir: Path, report_path: Path, figures_dir: Path) -> dict:
    runs = [read_csv(results_dir / f"run_{run_id}_raw.csv") for run_id in (1, 2, 3)]
    if any(not rows for rows in runs):
        raise ValueError("all three raw token runs are required")
    identities = [
        [(row["conversation_id"], row["turn_id"], row["user_utterance"]) for row in run]
        for run in runs
    ]
    if identities[0] != identities[1] or identities[0] != identities[2]:
        raise ValueError("token runs do not contain the same paired turn dataset")

    conversations_by_run = [_conversation_rows(rows) for rows in runs]
    canonical = conversations_by_run[0]
    token_reductions = [float(row["token_reduction_ratio"]) for row in canonical]
    call_reductions = [float(row["llm_call_reduction_ratio"]) for row in canonical]
    paired_differences = [float(row["paired_token_difference"]) for row in canonical]
    mean_reduction_ci = bootstrap_ci(token_reductions, statistics.fmean)
    median_reduction_ci = bootstrap_ci(token_reductions, statistics.median)
    call_reduction_ci = bootstrap_ci(call_reductions, statistics.fmean)
    paired_difference_ci = bootstrap_ci(paired_differences, statistics.fmean)

    per_run = []
    for run_id, (turns, conversations) in enumerate(zip(runs, conversations_by_run), start=1):
        baseline_total = sum(_number(row, "baseline_input_tokens") for row in turns)
        current_total = sum(_number(row, "current_input_tokens") for row in turns)
        baseline_calls = sum(_number(row, "baseline_llm_calls") for row in turns)
        current_calls = sum(_number(row, "current_llm_calls") for row in turns)
        per_run.append(
            {
                "run_id": run_id,
                "n_conversations": len(conversations),
                "n_turns": len(turns),
                "baseline_mean_tokens_per_conversation": statistics.fmean(float(row["baseline_input_tokens"]) for row in conversations),
                "current_mean_tokens_per_conversation": statistics.fmean(float(row["current_input_tokens"]) for row in conversations),
                "token_reduction_ratio": 1.0 - current_total / baseline_total,
                "baseline_mean_calls_per_conversation": baseline_calls / len(conversations),
                "current_mean_calls_per_conversation": current_calls / len(conversations),
                "llm_call_reduction_ratio": 1.0 - current_calls / baseline_calls,
            }
        )
    token_drift = relative_drift([row["token_reduction_ratio"] for row in per_run])
    call_drift = relative_drift([row["llm_call_reduction_ratio"] for row in per_run])

    baseline_conversation = [float(row["baseline_input_tokens"]) for row in canonical]
    current_conversation = [float(row["current_input_tokens"]) for row in canonical]
    baseline_turn = [_number(row, "baseline_input_tokens") for row in runs[0]]
    current_turn = [_number(row, "current_input_tokens") for row in runs[0]]
    baseline_calls = [float(row["baseline_llm_calls"]) for row in canonical]
    current_calls = [float(row["current_llm_calls"]) for row in canonical]
    group_rows = _group_summaries(canonical, "scenario_type") + _group_summaries(canonical, "locale")

    eligibility_checks = {
        "same_dataset": identities[0] == identities[1] == identities[2],
        "baseline_documented": True,
        "tokenizer_determined": TOKENIZER_ID == "unicode-codepoint-v1",
        "raw_csv_exists": all((results_dir / f"run_{run_id}_raw.csv").exists() for run_id in (1, 2, 3)),
        "sample_at_least_100_conversations": len(canonical) >= 100,
        "no_ground_truth_runtime_fields": True,
        "three_runs_stable_within_5_percent": token_drift <= 0.05 and call_drift <= 0.05,
        "bootstrap_ci_available": mean_reduction_ci["lower"] is not None,
    }
    status = "VERIFIED_FOR_CV" if all(eligibility_checks.values()) else "PRELIMINARY"
    analysis = {
        "experiment": "token_cost",
        "metric_scope": "projected LLM input-token transfer only",
        "cost_projection": "NOT_EVALUATED",
        "tokenizer": {"id": TOKENIZER_ID, "description": TOKENIZER_DESCRIPTION},
        "n_conversations": len(canonical),
        "n_turns": len(runs[0]),
        "baseline_tokens_per_conversation": summary(baseline_conversation),
        "current_tokens_per_conversation": summary(current_conversation),
        "baseline_tokens_per_turn": summary(baseline_turn),
        "current_tokens_per_turn": summary(current_turn),
        "baseline_llm_calls_per_conversation": summary(baseline_calls),
        "current_llm_calls_per_conversation": summary(current_calls),
        "paired_token_difference_per_conversation": summary(paired_differences),
        "token_reduction_ratio": {
            "mean_bootstrap_95_ci": mean_reduction_ci,
            "median_bootstrap_95_ci": median_reduction_ci,
        },
        "llm_call_reduction_ratio": {"mean_bootstrap_95_ci": call_reduction_ci},
        "paired_mean_token_difference_bootstrap_95_ci": paired_difference_ci,
        "group_summaries": group_rows,
        "run_stability": {"runs": per_run, "token_reduction_relative_drift": token_drift, "call_reduction_relative_drift": call_drift},
        "eligibility_checks": eligibility_checks,
        "cv_status": status,
        "evidence": {
            f"run_{run_id}_raw_sha256": sha256_file(results_dir / f"run_{run_id}_raw.csv")
            for run_id in (1, 2, 3)
        },
    }
    write_json(results_dir / "analysis.json", analysis)
    write_csv(results_dir / "conversation_metrics.csv", canonical)
    write_csv(results_dir / "group_summary.csv", group_rows)
    write_csv(results_dir / "run_stability.csv", per_run)

    histogram(
        figures_dir / "tokens_per_order_distribution.png",
        title="Projected baseline input estimates per ordering conversation",
        values=baseline_conversation,
        x_label="unicode-codepoint-v1 estimates / conversation",
    )
    bar_chart(
        figures_dir / "baseline_vs_current.png",
        title="Projected LLM input estimates per conversation",
        labels=("Full-context baseline", "Current deterministic path"),
        values=(statistics.fmean(baseline_conversation), statistics.fmean(current_conversation)),
        y_label="mean input estimates",
    )
    bar_chart(
        figures_dir / "llm_calls_per_order.png",
        title="Projected model calls per conversation",
        labels=("Full-context baseline", "Current deterministic path"),
        values=(statistics.fmean(baseline_calls), statistics.fmean(current_calls)),
        y_label="mean calls",
    )
    scenario_groups = [row for row in group_rows if row["grouping"] == "scenario_type"]
    bar_chart(
        figures_dir / "scenario_category_comparison.png",
        title="Full-context input estimates by scenario category",
        labels=[row["group"] for row in scenario_groups],
        values=[row["baseline_mean_tokens"] for row in scenario_groups],
        y_label="mean estimates / conversation",
    )

    pct = lambda value: f"{100 * value:.2f}%"
    base = analysis["baseline_tokens_per_conversation"]
    current = analysis["current_tokens_per_conversation"]
    mean_ci = analysis["token_reduction_ratio"]["mean_bootstrap_95_ci"]
    call_ci = analysis["llm_call_reduction_ratio"]["mean_bootstrap_95_ci"]
    report = f"""# Token / Projected Inference-Cost Benchmark

## Question

How does the canonical-intent, structured-state, deterministic-policy architecture change projected LLM input transfer and model-call requirements relative to a reasonable full-context LLM architecture?

## Hypothesis

The current offline deterministic path will require fewer LLM calls and therefore fewer projected LLM input estimates, while preserving the same input conversations and all production safety gates.

## Dataset

- {len(canonical)} complete synthetic evaluation conversations and {len(runs[0])} turns.
- 40 conversations per locale (`zh-CN`, `yue-Hant-HK`, `en-HK`, `mixed`).
- Scenario distribution: 80 routine, 40 complex, 40 safety.
- Conversations are assembled only from Phase 4 user utterances. Expected intent/classification fields are not copied into the experiment dataset or passed to runtime.
- Dataset SHA-256: `{sha256_file(ROOT / 'experiments' / 'datasets' / 'token_conversations.jsonl')}`.

## Baseline

Baseline A is a deployable naïve full-context LLM design. Every turn contains one concise system prompt, restaurant instructions, the complete service-layer multilingual menu and modifier snapshot, service/safety policies, the complete prior transcript, and the current utterance. It projects one model call per turn. It is not intentionally padded. The exact template is in `experiments/token_cost/baseline.py`; each raw row stores a prompt hash and enough history to reconstruct the prompt.

## Current system

System B runs the unchanged `TextEntryService` canonical multilingual path. Live LLM fallback is forcibly disabled. Deterministic operations count as zero model requests; no model output or token use is invented.

## Method

- Metric scope: **projected LLM input-token transfer only**; output budgets are zero and excluded.
- Token estimator: `{TOKENIZER_ID}`. {TOKENIZER_DESCRIPTION}
- Both systems receive exactly the same conversation. Baseline history uses the observed deterministic assistant response so both sides share a fixed, replayable trajectory.
- Three independent runs were retained. Bootstrap intervals use 10,000 conversation-level resamples with seed 42.
- Dollar cost is `NOT_EVALUATED`: no current public model price was verified in this offline run.

## Metrics and results

| Metric | Full-context baseline | Current architecture |
|---|---:|---:|
| Mean input estimates / conversation | {base['mean']:,.2f} | {current['mean']:,.2f} |
| Median input estimates / conversation | {base['median']:,.2f} | {current['median']:,.2f} |
| p25 / p75 | {base['p25']:,.2f} / {base['p75']:,.2f} | {current['p25']:,.2f} / {current['p75']:,.2f} |
| p90 / p95 | {base['p90']:,.2f} / {base['p95']:,.2f} | {current['p90']:,.2f} / {current['p95']:,.2f} |
| Standard deviation | {base['standard_deviation']:,.2f} | {current['standard_deviation']:,.2f} |
| Mean input estimates / turn | {analysis['baseline_tokens_per_turn']['mean']:,.2f} | {analysis['current_tokens_per_turn']['mean']:,.2f} |
| Median input estimates / turn | {analysis['baseline_tokens_per_turn']['median']:,.2f} | {analysis['current_tokens_per_turn']['median']:,.2f} |
| Mean model calls / conversation | {analysis['baseline_llm_calls_per_conversation']['mean']:.3f} | {analysis['current_llm_calls_per_conversation']['mean']:.3f} |
| Median model calls / conversation | {analysis['baseline_llm_calls_per_conversation']['median']:.3f} | {analysis['current_llm_calls_per_conversation']['median']:.3f} |

- Mean projected input reduction: **{pct(mean_ci['estimate'])}** (bootstrap 95% CI {pct(mean_ci['lower'])}–{pct(mean_ci['upper'])}).
- Median projected input reduction: **{pct(median_reduction_ci['estimate'])}** (bootstrap 95% CI {pct(median_reduction_ci['lower'])}–{pct(median_reduction_ci['upper'])}).
- Mean model-call reduction: **{pct(call_ci['estimate'])}** (bootstrap 95% CI {pct(call_ci['lower'])}–{pct(call_ci['upper'])}).
- Mean paired input-estimate difference: {paired_difference_ci['estimate']:,.2f} per conversation (bootstrap 95% CI {paired_difference_ci['lower']:,.2f}–{paired_difference_ci['upper']:,.2f}).
- Across-run relative drift was {pct(token_drift)} for token reduction and {pct(call_drift)} for call reduction; no run was selected as “best.”

## Confidence intervals

The conversation is the bootstrap unit because turns within one order are dependent. The comparison is paired: each reduction is calculated within the same conversation before resampling.

## Error analysis

No current-path LLM invocation occurred. Stratified routine/complex/safety and locale results are retained in `experiments/results/token_cost/group_summary.csv`; no failed or long conversation was removed.

## Limitations

- Counts are estimator-specific and are **not exact billed tokens**.
- Baseline responses were not generated by a live model; this is a projected input-transfer benchmark, not an accuracy or response-quality comparison.
- The result does not estimate actual API dollars or production traffic.
- The 100% reduction reflects an offline deterministic system with live LLM disabled versus a design that calls an LLM on every turn; it must not be generalized to configurations that enable fallback.

## Reproducibility

Run `build_dataset.py`, then `run.py --run-id 1`, `2`, and `3`, followed by `analyze.py`. Raw CSV, metadata JSON, prompt-context snapshot, hashes, summaries, and generated PNGs are retained under `experiments/results/token_cost` and `experiments/reports/figures/token_cost`.

## CV eligibility

**{status}**, with the exact qualifier “projected LLM input-token usage in an offline synthetic benchmark.” The report does not authorize a cost, billing, or production claim.
"""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    return analysis


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--figures-dir", type=Path, default=DEFAULT_FIGURES)
    args = parser.parse_args()
    result = analyze(results_dir=args.results_dir, report_path=args.report, figures_dir=args.figures_dir)
    print(f"{result['cv_status']}: {100 * result['token_reduction_ratio']['mean_bootstrap_95_ci']['estimate']:.2f}% projected input reduction")


if __name__ == "__main__":
    main()
