from __future__ import annotations

import argparse
import hashlib
import statistics
from collections import defaultdict
from pathlib import Path

import numpy as np

from experiments.common.charts import bar_chart, histogram
from experiments.common.io import read_csv, write_csv, write_json
from experiments.common.metadata import ROOT, sha256_file
from experiments.common.stats import relative_drift, summary


DEFAULT_RESULTS = ROOT / "experiments" / "results" / "latency"
DEFAULT_REPORT = ROOT / "experiments" / "reports" / "latency_benchmark.md"
DEFAULT_FIGURES = ROOT / "experiments" / "reports" / "figures" / "latency"
RESAMPLES = 10_000
SEED = 42


def bootstrap_location(values: list[float], *, quantile: float, seed: int = SEED) -> dict:
    data = np.asarray(values, dtype=float)
    if data.size == 0:
        return {"estimate": None, "lower": None, "upper": None, "resamples": RESAMPLES, "seed": seed}
    rng = np.random.default_rng(seed)
    estimates = np.empty(RESAMPLES, dtype=float)
    chunk = 250
    for start in range(0, RESAMPLES, chunk):
        size = min(chunk, RESAMPLES - start)
        indexes = rng.integers(0, data.size, size=(size, data.size))
        estimates[start : start + size] = np.quantile(data[indexes], quantile, axis=1)
    return {
        "estimate": float(np.quantile(data, quantile)),
        "lower": float(np.quantile(estimates, 0.025)),
        "upper": float(np.quantile(estimates, 0.975)),
        "resamples": RESAMPLES,
        "seed": seed,
    }


def _case_medians(runs: list[list[dict]], *, id_key: str, value_key: str, predicate=lambda row: True) -> list[dict]:
    grouped: dict[str, list[tuple[dict, float]]] = defaultdict(list)
    for rows in runs:
        for row in rows:
            if predicate(row) and row.get(value_key, "") not in {"", None}:
                grouped[row[id_key]].append((row, float(row[value_key])))
    output = []
    for case_id, observations in sorted(grouped.items()):
        template = observations[0][0]
        output.append(
            {
                "case_id": case_id,
                "n_runs": len(observations),
                "case_median_ms": statistics.median(value for _, value in observations),
                "locale": template.get("locale", ""),
                "category_group": template.get("category_group", ""),
                "semantic_category": template.get("semantic_category", ""),
                "decision_class": template.get("decision_class", ""),
                "dataset_source": template.get("dataset_source", ""),
                "outcome": template.get("outcome", ""),
                "stage": value_key.removesuffix("_ms"),
            }
        )
    return output


def _latency_summary(rows: list[dict], label: str) -> dict:
    values = [float(row["case_median_ms"]) for row in rows]
    return {
        "path": label,
        **summary(values),
        "median_bootstrap_95_ci": bootstrap_location(values, quantile=0.5, seed=SEED),
        "p95_bootstrap_95_ci": bootstrap_location(values, quantile=0.95, seed=SEED + 1),
    }


def _grouped(rows: list[dict], key: str, prefix: str) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        value = str(row.get(key) or "UNCLASSIFIED")
        groups[value].append(row)
    return [{"grouping": key, "group": group, **_latency_summary(items, f"{prefix}/{group}")} for group, items in sorted(groups.items())]


def _run_metrics(rows: list[dict], value_key: str, predicate=lambda row: True) -> dict:
    values = [float(row[value_key]) for row in rows if predicate(row) and row.get(value_key, "") not in {"", None}]
    return summary(values)


def _phase5_group(category: str) -> str:
    safety = {"allergy", "attack", "bypass", "card", "complaint", "cross", "cross_tenant", "dispute", "forge", "guarantee", "human", "other_order", "refund", "secret"}
    ambiguity = {"ambiguous_item", "ambiguous_quantity", "bad_modifier", "correction", "missing_item", "question_add", "sold_out", "unsupported"}
    if category in safety:
        return "safety"
    if category in ambiguity:
        return "ambiguity"
    return "routine"


def analyze(*, results_dir: Path, report_path: Path, figures_dir: Path) -> dict:
    text_runs = [read_csv(results_dir / f"text_run_{run_id}_raw.csv") for run_id in (1, 2, 3)]
    replay_runs = [read_csv(results_dir / f"replay_run_{run_id}_raw.csv") for run_id in (1, 2, 3)]
    text_ids = [[row["case_id"] for row in rows] for rows in text_runs]
    replay_ids = [[(row["record_type"], row["scenario_id"]) for row in rows] for rows in replay_runs]
    if not (text_ids[0] == text_ids[1] == text_ids[2] and replay_ids[0] == replay_ids[1] == replay_ids[2]):
        raise ValueError("latency runs do not contain identical measurement cases")

    text_cases = _case_medians(text_runs, id_key="case_id", value_key="latency_ms")
    for row in text_cases:
        # category_group is present in raw text data; kept explicit for audit.
        row["category_group"] = row["category_group"] or "routine"
    text_overall = _latency_summary(text_cases, "local_text_decision")
    text_groups = _grouped(text_cases, "decision_class", "local_text_decision")
    text_groups += _grouped(text_cases, "category_group", "local_text_decision")
    text_groups += _grouped(text_cases, "dataset_source", "local_text_decision")

    replay_audio_runs = []
    for run in replay_runs:
        materialized = []
        for raw in run:
            item = dict(raw)
            item["category_group"] = _phase5_group(item.get("semantic_category", ""))
            materialized.append(item)
        replay_audio_runs.append(materialized)
    audio_predicate = lambda row: row["record_type"] == "audio_pipeline"
    tts_predicate = lambda row: row["record_type"] == "replay_tts"
    stage_keys = ("audio_validation_ms", "replay_asr_ms", "text_decision_ms", "end_to_end_ms")
    replay_stage_cases: dict[str, list[dict]] = {
        key: _case_medians(replay_audio_runs, id_key="scenario_id", value_key=key, predicate=audio_predicate)
        for key in stage_keys
    }
    replay_stage_cases["replay_tts_ms"] = _case_medians(
        replay_audio_runs, id_key="scenario_id", value_key="replay_tts_ms", predicate=tts_predicate
    )
    replay_summaries = [_latency_summary(rows, key.removesuffix("_ms")) for key, rows in replay_stage_cases.items()]
    replay_e2e = replay_stage_cases["end_to_end_ms"]
    replay_groups = _grouped(replay_e2e, "decision_class", "synthetic_replay_end_to_end")
    replay_groups += _grouped(replay_e2e, "category_group", "synthetic_replay_end_to_end")
    replay_groups += _grouped(replay_e2e, "outcome", "synthetic_replay_end_to_end")

    text_run_stability = []
    replay_run_stability = []
    for run_id, rows in enumerate(text_runs, start=1):
        metrics = _run_metrics(rows, "latency_ms")
        text_run_stability.append({"run_id": run_id, "p50_ms": metrics["p50"], "p95_ms": metrics["p95"], "p99_ms": metrics["p99"], "max_ms": metrics["max"]})
    for run_id, rows in enumerate(replay_audio_runs, start=1):
        metrics = _run_metrics(rows, "end_to_end_ms", audio_predicate)
        replay_run_stability.append({"run_id": run_id, "p50_ms": metrics["p50"], "p95_ms": metrics["p95"], "p99_ms": metrics["p99"], "max_ms": metrics["max"]})
    stability = {
        "local_text": {
            "runs": text_run_stability,
            "p50_relative_drift": relative_drift([row["p50_ms"] for row in text_run_stability]),
            "p95_relative_drift": relative_drift([row["p95_ms"] for row in text_run_stability]),
        },
        "synthetic_replay_end_to_end": {
            "runs": replay_run_stability,
            "p50_relative_drift": relative_drift([row["p50_ms"] for row in replay_run_stability]),
            "p95_relative_drift": relative_drift([row["p95_ms"] for row in replay_run_stability]),
        },
    }

    local_p50_stable = stability["local_text"]["p50_relative_drift"] <= 0.05
    local_p95_stable = stability["local_text"]["p95_relative_drift"] <= 0.05
    local_status = "VERIFIED_FOR_CV" if local_p50_stable and local_p95_stable else "PRELIMINARY_CV_WITH_QUALIFIER"
    replay_status = "PRELIMINARY_CV_WITH_QUALIFIER"
    analysis = {
        "experiment": "latency",
        "aggregation": "case-level median across three sequential runs; every run and raw timing is retained",
        "timer": "time.perf_counter_ns",
        "database": "SQLite only",
        "local_text_decision": {
            "summary": text_overall,
            "groups": text_groups,
            "cv_status": local_status,
            "qualifier": "local decision benchmark; excludes network, ASR, live LLM, and TTS",
        },
        "synthetic_replay_pipeline": {
            "stage_summaries": replay_summaries,
            "groups": replay_groups,
            "cv_status": replay_status,
            "qualifier": "synthetic Replay fixture pipeline; not real ASR/TTS or phone latency",
            "audio_end_to_end_includes_tts": False,
        },
        "real_direct_llm_latency": {
            "status": "NOT_EVALUATED",
            "reason": "A controlled live-provider comparison is required; ALLOW_LIVE_LLM remained false.",
        },
        "real_speech_latency": {
            "status": "NOT_EVALUATED",
            "reason": "No real ASR, TTS, PSTN, SIP, WebRTC, call, or customer was used.",
        },
        "stability": stability,
        "evidence": {
            **{f"text_run_{run_id}_raw_sha256": sha256_file(results_dir / f"text_run_{run_id}_raw.csv") for run_id in (1, 2, 3)},
            **{f"replay_run_{run_id}_raw_sha256": sha256_file(results_dir / f"replay_run_{run_id}_raw.csv") for run_id in (1, 2, 3)},
        },
    }
    write_json(results_dir / "latency_analysis.json", analysis)
    write_csv(results_dir / "text_case_medians.csv", text_cases)
    write_csv(results_dir / "text_group_summary.csv", text_groups)
    write_csv(results_dir / "replay_stage_summary.csv", replay_summaries)
    write_csv(results_dir / "replay_group_summary.csv", replay_groups)
    write_csv(results_dir / "run_stability.csv", [
        *({"benchmark": "local_text", **row} for row in text_run_stability),
        *({"benchmark": "synthetic_replay_end_to_end", **row} for row in replay_run_stability),
    ])
    for key, rows in replay_stage_cases.items():
        write_csv(results_dir / f"{key.removesuffix('_ms')}_case_medians.csv", rows)

    histogram(
        figures_dir / "local_decision_latency_distribution.png",
        title="Local decision latency (case-level median across 3 runs)",
        values=[row["case_median_ms"] for row in text_cases],
        x_label="milliseconds",
    )
    decision_rows = [row for row in text_groups if row["grouping"] == "decision_class"]
    bar_chart(
        figures_dir / "local_p50_p95_by_path.png",
        title="Local decision p50 / p95 by safety path",
        labels=[f"{row['group']} p{percentile}" for row in decision_rows for percentile in (50, 95)],
        values=[row[f"p{percentile}"] for row in decision_rows for percentile in (50, 95)],
        y_label="milliseconds",
    )
    category_rows = [row for row in text_groups if row["grouping"] == "category_group"]
    bar_chart(
        figures_dir / "local_category_comparison.png",
        title="Local decision p50 / p95 by category",
        labels=[f"{row['group']} p{percentile}" for row in category_rows for percentile in (50, 95)],
        values=[row[f"p{percentile}"] for row in category_rows for percentile in (50, 95)],
        y_label="milliseconds",
    )
    bar_chart(
        figures_dir / "replay_stage_p50_p95.png",
        title="Synthetic Replay stage p50 / p95",
        labels=[f"{row['path']} p{percentile}" for row in replay_summaries for percentile in (50, 95)],
        values=[row[f"p{percentile}"] for row in replay_summaries for percentile in (50, 95)],
        y_label="milliseconds",
    )
    histogram(
        figures_dir / "replay_end_to_end_distribution.png",
        title="Synthetic Replay input pipeline latency",
        values=[row["case_median_ms"] for row in replay_e2e],
        x_label="milliseconds",
    )

    fmt_ci = lambda value: f"{value['estimate']:.3f} ms (95% CI {value['lower']:.3f}–{value['upper']:.3f})"
    stage_by_path = {row["path"]: row for row in replay_summaries}
    report = f"""# Latency Benchmark

## Question

What is the measured local decision latency of the current text system, and what is the component latency of the existing fully offline Synthetic Replay speech fixture pipeline?

## Hypothesis

The deterministic local path should complete on a local machine without network or live-model delay. Replay timings should remain explicitly separate from real speech latency.

## Dataset

- Local text: 1,228 cases per run (360 Phase 4 scenarios plus 868 turns from 160 complete conversations), three sequential runs, 20 excluded warm-ups per run.
- Synthetic Replay input: 240 Phase 5 fixtures per run, three sequential runs, 20 excluded warm-ups per run.
- Replay TTS: 15 reviewed tone fixtures × 7 repetitions = 105 timings per run, plus 20 excluded warm-ups.
- The measurement unit in the primary summary is each case's median across the three runs; raw timings for every run remain available.

## Baseline

A real direct-LLM latency baseline is **NOT_EVALUATED**. `ALLOW_LIVE_LLM=false` was not changed. A controlled live-provider benchmark would be required for that comparison.

## Current system

Local text covers `raw text → locale → canonical parser → safety decision → state transition → response object`. It includes local SQLite state work but excludes network, ASR, live LLM, and TTS.

Synthetic Replay covers `audio bytes → AudioValidator/normalizer → Replay ASR fixture lookup → TranscriptEnvelope → TextEntryService → decision`. Replay TTS fixture lookup is measured as a separate optional output stage; it is not included in audio end-to-end input latency.

## Method

- `time.perf_counter_ns()` surrounds only the relevant call.
- Python startup, imports, database migration/seeding, fixture/file loading, setup turns, logging, and warm-up are outside the timed region.
- Stage timing uses experiment-only wrappers; production classes and safety semantics are unchanged.
- Median and p95 intervals use 10,000 bootstrap resamples with seed 42/43 at the case level.
- All results in this report are SQLite measurements; no PostgreSQL result is mixed in.

## Metrics and results — local decision latency

N = {text_overall['n']} cases. Primary aggregation: case-level median across three runs.

| Metric | Value |
|---|---:|
| Mean | {text_overall['mean']:.3f} ms |
| Median / p50 | {text_overall['median']:.3f} ms |
| p90 | {text_overall['p90']:.3f} ms |
| p95 | {text_overall['p95']:.3f} ms |
| p99 | {text_overall['p99']:.3f} ms |
| Max | {text_overall['max']:.3f} ms |
| Standard deviation | {text_overall['standard_deviation']:.3f} ms |

- Median: {fmt_ci(text_overall['median_bootstrap_95_ci'])}.
- p95: {fmt_ci(text_overall['p95_bootstrap_95_ci'])}.
- Decision-path and routine/ambiguity/safety breakdowns, with separate CIs, are in `experiments/results/latency/text_group_summary.csv`.

## Metrics and results — Synthetic Replay Pipeline Latency

| Stage | N | p50 | p95 | p99 | Max |
|---|---:|---:|---:|---:|---:|
"""
    for row in replay_summaries:
        report += f"| {row['path']} | {row['n']} | {row['p50']:.3f} ms | {row['p95']:.3f} ms | {row['p99']:.3f} ms | {row['max']:.3f} ms |\n"
    report += f"""

- Synthetic Replay end-to-end median: {fmt_ci(stage_by_path['end_to_end']['median_bootstrap_95_ci'])}.
- Synthetic Replay end-to-end p95: {fmt_ci(stage_by_path['end_to_end']['p95_bootstrap_95_ci'])}.
- Stage, decision-path, outcome, and category tables are retained in CSV and JSON.

## Confidence intervals and stability

Local per-run p50 values were {', '.join(f"{row['p50_ms']:.3f}" for row in text_run_stability)} ms; per-run p95 values were {', '.join(f"{row['p95_ms']:.3f}" for row in text_run_stability)} ms. Relative drift was {100 * stability['local_text']['p50_relative_drift']:.2f}% for p50 and {100 * stability['local_text']['p95_relative_drift']:.2f}% for p95.

Synthetic Replay end-to-end p50 relative drift was {100 * stability['synthetic_replay_end_to_end']['p50_relative_drift']:.2f}%; p95 relative drift was {100 * stability['synthetic_replay_end_to_end']['p95_relative_drift']:.2f}%.

The third local run slowed near its final measurement block, producing p95 drift above the preregistered 5% investigation threshold. That run is retained and included in the case-level aggregation; no fastest run was selected. This instability limits the local latency CV status.

## Error analysis

- All four local decision classes were retained: AUTO_DRAFT, CONFIRM, HANDOFF, and REFUSE.
- Invalid Replay inputs remain in end-to-end timing. Missing stages are blank rather than replaced with zero.
- Replay ASR/TTS times measure deterministic fixture validation and lookup, not recognition or speech synthesis.

## Limitations

- This is one Windows host and temporary SQLite, not a production deployment or capacity test.
- No network, real LLM, real ASR, real TTS, caller audio, telephony, or streaming barge-in is measured.
- End-to-end Replay input timing excludes optional TTS; the TTS stage is shown separately.
- A real direct-LLM latency comparison requires a controlled live-provider benchmark and is not measured in this offline experiment.

## Reproducibility

Run each latency runner with `--run-id 1`, `2`, and `3`, then run `analyze.py`. Raw nanosecond/millisecond CSV, metadata JSON, case-level summaries, bootstrap intervals, hashes, and PNG charts are retained.

## CV eligibility

- Local decision latency: **{local_status}** with the mandatory qualifier “local benchmark.” p95 stability exceeded the 5% investigation threshold, so the p50/p95 pair is not promoted as a fully verified CV claim in this run.
- Synthetic Replay latency: **{replay_status}**, only with the qualifier “synthetic Replay benchmark.”
- Real speech/phone latency: **NOT_EVALUATED / NOT_FOR_CV**.
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
    local = result["local_text_decision"]["summary"]
    print(f"local p50={local['p50']:.3f} ms p95={local['p95']:.3f} ms; {result['local_text_decision']['cv_status']}")


if __name__ == "__main__":
    main()
