from __future__ import annotations

import argparse
import json
from pathlib import Path

from experiments.common.io import write_csv, write_json
from experiments.common.metadata import EXPERIMENT_BASE_SHA, ROOT


DEFAULT_OUTPUT = ROOT / "experiments" / "reports" / "resume_metrics_review.md"
DEFAULT_RESULTS = ROOT / "experiments" / "results"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_review(*, results_dir: Path, output_path: Path) -> list[dict]:
    token = load(results_dir / "token_cost" / "analysis.json")
    latency = load(results_dir / "latency" / "latency_analysis.json")
    barge = load(results_dir / "barge_in" / "classifier_analysis.json")
    recovery = load(results_dir / "barge_in" / "recovery_analysis.json")
    regression = load(results_dir / "regression_summary.json")
    metadata = load(results_dir / "token_cost" / "run_1_metadata.json")
    token_ci = token["token_reduction_ratio"]["mean_bootstrap_95_ci"]
    call_ci = token["llm_call_reduction_ratio"]["mean_bootstrap_95_ci"]
    local = latency["local_text_decision"]["summary"]
    replay_stages = {row["path"]: row for row in latency["synthetic_replay_pipeline"]["stage_summaries"]}
    bmetrics = barge["selected_test_metrics"]
    metrics = [
        {
            "metric": "Projected LLM input-token transfer reduction",
            "value": f"{100 * token_ci['estimate']:.2f}% (95% bootstrap CI {100 * token_ci['lower']:.2f}%–{100 * token_ci['upper']:.2f}%) across {token['n_conversations']} conversations / {token['n_turns']} turns",
            "evidence": "experiments/results/token_cost/analysis.json; three run_*_raw.csv files",
            "qualifier": "offline synthetic conversations; full-context always-LLM baseline; unicode-codepoint-v1 estimator; projected input only; not billed tokens",
            "status": "VERIFIED_FOR_CV",
            "cv_action": "INCLUDE",
        },
        {
            "metric": "Projected LLM-call requirement reduction",
            "value": f"{100 * call_ci['estimate']:.2f}%; mean {token['baseline_llm_calls_per_conversation']['mean']:.3f} → {token['current_llm_calls_per_conversation']['mean']:.3f} calls/conversation",
            "evidence": "experiments/results/token_cost/analysis.json",
            "qualifier": "offline deterministic configuration with live LLM disabled versus one baseline call per turn",
            "status": "VERIFIED_FOR_CV",
            "cv_action": "INCLUDE_WITH_TOKEN_CLAIM",
        },
        {
            "metric": "Local text decision latency",
            "value": f"p50 {local['p50']:.3f} ms; p95 {local['p95']:.3f} ms; N={local['n']} case-level medians across 3 runs",
            "evidence": "experiments/results/latency/latency_analysis.json; text_run_*_raw.csv",
            "qualifier": f"local SQLite benchmark; p50 run drift {100 * latency['stability']['local_text']['p50_relative_drift']:.2f}%, p95 drift {100 * latency['stability']['local_text']['p95_relative_drift']:.2f}% (>5%)",
            "status": "PRELIMINARY_CV_WITH_QUALIFIER",
            "cv_action": "DO_NOT_INCLUDE_THIS_ROUND",
        },
        {
            "metric": "Synthetic Replay input pipeline latency",
            "value": f"p50 {replay_stages['end_to_end']['p50']:.3f} ms; p95 {replay_stages['end_to_end']['p95']:.3f} ms; N={replay_stages['end_to_end']['n']}",
            "evidence": "experiments/results/latency/latency_analysis.json; replay_run_*_raw.csv",
            "qualifier": "Synthetic Replay fixture lookup, text decision, and audit; optional Replay TTS excluded; not real ASR/TTS/phone latency",
            "status": "PRELIMINARY_CV_WITH_QUALIFIER",
            "cv_action": "DO_NOT_INCLUDE_THIS_ROUND",
        },
        {
            "metric": "Synthetic interruption classifier",
            "value": f"F1 {bmetrics['f1']:.3f}; precision {bmetrics['precision']:.3f}; recall {bmetrics['recall']:.3f}; FPR {100 * bmetrics['false_positive_rate']:.2f}%; N={bmetrics['n']}",
            "evidence": "experiments/results/barge_in/classifier_analysis.json; selected_test_predictions.csv",
            "qualifier": "programmatic overlapping signals; no intelligible speech or ASR; FPR failed preregistered ≤15% threshold",
            "status": "NOT_FOR_CV",
            "cv_action": "EXCLUDE",
        },
        {
            "metric": "Synthetic dialogue-state recovery",
            "value": f"{recovery['successes']}/{recovery['n']} ({100 * recovery['recovery_success_rate']:.2f}%), 25 each TP/FP/FN/TN",
            "evidence": "experiments/results/barge_in/recovery_analysis.json; recovery_raw.csv",
            "qualifier": "synthetic state-machine test; classifier advisory only; not playback interruption or production barge-in",
            "status": "PRELIMINARY_CV_WITH_QUALIFIER",
            "cv_action": "DO_NOT_INCLUDE_BECAUSE_UPSTREAM_DETECTOR_FAILED",
        },
        {
            "metric": "360 multilingual text scenarios",
            "value": "360/360 intent and classification matches in both auto and assisted modes; 0 wrong mutations / confirmation bypasses",
            "evidence": "evaluation/phase4_multilingual_text.jsonl; explicit Phase 4 regression on 2026-08-04",
            "qualifier": "synthetic/offline multilingual evaluation",
            "status": "VERIFIED_FOR_CV",
            "cv_action": "RETAIN_EXISTING_CV_CLAIM",
        },
        {
            "metric": "240 synthetic Replay speech-pipeline scenarios",
            "value": "240 scenarios; 0 wrong mutations, confirmation bypasses, live-provider invocations, or live-LLM triggers",
            "evidence": "evaluation/phase5_speech_pipeline.jsonl; explicit Phase 5 regression on 2026-08-04",
            "qualifier": "synthetic Replay Provider; not ASR/TTS accuracy or real speech",
            "status": "VERIFIED_FOR_CV",
            "cv_action": "RETAIN_EXISTING_CV_CLAIM",
        },
        {
            "metric": "Actual API cost / production bill",
            "value": "NOT_EVALUATED",
            "evidence": "No verified price source and no live provider call",
            "qualifier": "projected input estimates only",
            "status": "NOT_FOR_CV",
            "cv_action": "EXCLUDE",
        },
        {
            "metric": "Real phone / speech / ASR / TTS latency or accuracy",
            "value": "NOT_EVALUATED",
            "evidence": "provider metadata: no live ASR/TTS, PSTN, SIP, WebRTC, call, or customer",
            "qualifier": "none available",
            "status": "NOT_FOR_CV",
            "cv_action": "EXCLUDE",
        },
        {
            "metric": "Real-world barge-in accuracy / success",
            "value": "NOT_IMPLEMENTED / NOT_EVALUATED",
            "evidence": "prototype is isolated under experiments/barge_in",
            "qualifier": "synthetic state-machine and signal experiments only",
            "status": "NOT_FOR_CV",
            "cv_action": "EXCLUDE",
        },
        {
            "metric": "Restaurant success, complaint, refund, or business cost rate",
            "value": "NOT_EVALUATED",
            "evidence": "No real restaurant or customer data used",
            "qualifier": "none available",
            "status": "NOT_FOR_CV",
            "cv_action": "EXCLUDE",
        },
    ]
    write_json(results_dir / "experiment_summary.json", metrics)
    write_csv(results_dir / "experiment_summary.csv", metrics)
    rows = "\n".join(
        f"| {item['metric']} | {item['value']} | {item['evidence']} | {item['qualifier']} | **{item['status']}** |"
        for item in metrics
    )
    report = f"""# Resume Metrics Review

## Experimental baseline

- Experiment base SHA: `{EXPERIMENT_BASE_SHA}` (Phase 5 HEAD; Phase 5 was required for Replay and was not merged or rewritten).
- Experiment branch: `experiment/performance-and-interruption-benchmarks`.
- Machine: {metadata['os']}; {metadata['cpu']}; {metadata['logical_cpu_count']} logical CPUs; {metadata['memory_bytes'] / (1024 ** 3):.2f} GiB RAM.
- Python: {metadata['python_version']}.
- Provider configuration: live LLM disabled; token and local latency use no ASR/TTS; speech latency uses Replay ASR/TTS fixture providers only.
- Production regression: final `check_all.ps1 -Build` passed ({regression['final_check_all']['backend_pytest']['passed']} backend tests, {regression['final_check_all']['frontend_vitest']['tests_passed']} frontend tests, TypeScript and build); explicit Phase 4, Phase 5, and dialogue v3 evaluations passed.
- Audit note: the first full check had one nondeterministic SQLite concurrency failure; the exact failure is retained in `experiments/results/regression_summary.json`, passed 3/3 isolated retries, and the complete rerun passed.

## Qualification table

| Metric | Value | Evidence | Qualifier | Status |
|---|---|---|---|---|
{rows}

## VERIFIED_FOR_CV

The only **new** CV claim authorized this round is the paired Token/model-call result. Existing verified 360-text-scenario and 240-Replay-scenario claims remain. The CV wording must say **projected**, **offline/synthetic**, and must not imply billed tokens or an actual API bill.

Authorized English wording:

> Against a documented full-context LLM baseline, reduced projected LLM input-token usage and model-call requirements by 100% across 160 synthetic ordering conversations (868 turns; offline deterministic configuration; 95% bootstrap CI 100–100%).

Authorized Chinese wording:

> 相较有文档定义的完整上下文 LLM 基线，在 160 组合成订餐会话（868 轮）的离线确定性配置中，预估 LLM 输入 Token 传输量与模型调用需求均降低 100%（Bootstrap 95% CI：100%–100%）。

## PRELIMINARY_CV_WITH_QUALIFIER

- Local p50/p95 values remain preliminary because p95 drift across runs was {100 * latency['stability']['local_text']['p95_relative_drift']:.2f}%.
- Synthetic Replay latency is reproducible but is not real speech latency.
- Recovery was 100/100 only in a synthetic dialogue-state suite. Because the upstream detector failed its FPR gate, it is not promoted in this CV update.

## NOT_FOR_CV

- Synthetic interruption detector: F1 {bmetrics['f1']:.3f}, but FPR {100 * bmetrics['false_positive_rate']:.2f}% exceeded the preregistered limit.
- Real phone/speech latency, real ASR/TTS accuracy, real barge-in, production success/complaint rate, actual restaurant cost, and actual API billing were not evaluated.

## Leakage and baseline audit

- Baseline and current receive identical user conversations; raw turn identities match across three runs.
- Expected Phase 4 intent/classification values are discarded when the Token dataset is constructed and are never passed to runtime.
- Replay receives only fixture audio/metadata/ID; `expectedTranscript` is never passed to the provider.
- Barge-in model features exclude label, semantic text, locale, category, template ID, SNR, onset, and waveform seed.
- The rejected category-unbalanced pilot split is retained rather than deleted; its test set was not opened.
- No experiment path changes `AUTO_DRAFT`, `CONFIRM`, `HANDOFF`, or `REFUSE`; no experiment is imported by production.

## CV update decision

- Replace only the qualitative efficiency bullet with the authorized paired Token/model-call claim.
- Keep the five-bullet project structure.
- Retain the existing 360 multilingual text and 240 synthetic Replay facts.
- Do not add local latency, synthetic detector F1, recovery, real-speech, or cost claims this round.
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    metrics = build_review(results_dir=args.results_dir, output_path=args.output)
    print(f"wrote {len(metrics)} audited metrics to {args.output}")


if __name__ == "__main__":
    main()
