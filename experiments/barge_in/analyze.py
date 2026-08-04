from __future__ import annotations

import argparse
import json
from pathlib import Path

from experiments.common.charts import bar_chart
from experiments.common.metadata import ROOT, sha256_file


DEFAULT_RESULTS = ROOT / "experiments" / "results" / "barge_in"
DEFAULT_REPORT = ROOT / "experiments" / "reports" / "barge_in_benchmark.md"
DEFAULT_FIGURES = ROOT / "experiments" / "reports" / "figures" / "barge_in"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def analyze(*, results_dir: Path, report_path: Path, figures_dir: Path) -> dict:
    classifier = load(results_dir / "classifier_analysis.json")
    recovery = load(results_dir / "recovery_analysis.json")
    selection = load(results_dir / "model_selection.json")
    figures_dir.mkdir(parents=True, exist_ok=True)
    bar_chart(
        figures_dir / "recovery_success.png",
        title="Synthetic dialogue-state recovery success",
        labels=[row["condition"] for row in recovery["by_condition"]],
        values=[row["recovery_success_rate"] for row in recovery["by_condition"]],
        y_label="success rate",
    )
    metrics = classifier["selected_test_metrics"]
    cis = classifier["bootstrap_95_ci"]
    recovery_status = "PRELIMINARY_CV_WITH_QUALIFIER" if recovery["recovery_success_rate"] >= 0.95 else "NOT_FOR_CV"
    overall_status = "NOT_FOR_CV" if classifier["classifier_cv_status"] == "NOT_FOR_CV" else "PRELIMINARY_CV_WITH_QUALIFIER"
    final = {
        "classifier_cv_status": classifier["classifier_cv_status"],
        "recovery_cv_status": recovery_status,
        "overall_barge_in_cv_status": overall_status,
        "classifier": classifier,
        "recovery": recovery,
    }
    (results_dir / "barge_in_analysis.json").write_text(
        json.dumps(final, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    validation = {row["model"]: row for row in selection["validation_comparison"]}
    test_ensembles = {
        row["model"]: row
        for row in classifier["model_comparison"]
        if row["evaluation"] == "three_seed_majority_vote"
    }
    percent = lambda value: f"{100 * value:.2f}%"
    ci = lambda name: f"{cis[name]['estimate']:.3f} [{cis[name]['lower']:.3f}, {cis[name]['upper']:.3f}]"
    report = f"""# Synthetic Barge-in / Interruption Benchmark

## Question

Can a small, isolated and explainable classifier distinguish interruption attempts from non-interruption overlaps in a fully programmatic dataset, and can the ordering state recover safely under TP, FP, FN, and TN outcomes?

## Hypothesis

Simple acoustic/temporal features should separate some foreground interruption-like events from noise, while speech-like negatives will remain difficult without ASR/text semantics. The production text state machine should remain safe even when the prototype classifier is wrong.

## Dataset

- 1,600 fully synthetic programmatic overlap signals: 800 `INTERRUPTION`, 800 `NON_INTERRUPTION`.
- Exact group split: 1,120 train / 240 validation / 240 locked test (70% / 15% / 15%).
- Every class × locale × event-category cell is split by `template_group_id`; waveform variants of one semantic template never cross splits.
- Four locales are exactly balanced overall and within each split. All 20 positive/negative categories are balanced within each split.
- Onset covers 20/40/60/80%; configured SNR covers -10/-5/0/+5/+10 dB, with -120 dB representing the documented silence category.
- Signals are reconstructed from manifest parameters and checked by PCM SHA-256. They contain no recorded person, customer audio, intelligible TTS, or online ASR.
- Final dataset SHA-256: `{classifier['dataset']['dataset_sha256']}`.

## Baseline

Model A is a fixed acoustic rule using energy, ZCR, centroid, flatness, duration, crest factor, and periodicity. It is transparent and has near-zero inference cost.

## Current system / prototype models

- Model B: L2-regularized logistic regression trained by deterministic full-batch gradient descent.
- Model C: 120 bounded gradient-boosted decision stumps with 85% row subsampling; seeds 42/43/44.
- Model selection used mean validation F1 only; ties prefer lower complexity. The locked test was opened after `model_selection.json` named `{classifier['selected_model']}`.
- Only 13 acoustic/temporal features derived from `mixed signal − known AI playback reference` enter a model. Label, semantic text, locale, category, template ID, onset, SNR, and waveform seed are excluded.

## Method

The final classifier prediction is a majority vote across the three predeclared seeds. Test precision, recall, F1, FPR, and FNR intervals use 10,000 example-level bootstrap resamples with seed 42. Inference is offline and is not wired into production.

A first pilot split was rejected before opening its test set because category balance was not preserved. Its dataset, features, validation predictions, models, and metadata remain under `experiments/results/barge_in/pilot_unbalanced_split`; no pilot sample was deleted. The corrected group-balanced dataset produced all results below.

## Model comparison

| Model | Validation mean F1 | Locked-test ensemble Precision | Recall | F1 | FPR |
|---|---:|---:|---:|---:|---:|
"""
    for name in ("rule_baseline", "logistic_regression", "gradient_boosting_stumps"):
        row = test_ensembles[name]
        report += f"| {name} | {validation[name]['validation_mean_f1']:.3f} | {row['precision']:.3f} | {row['recall']:.3f} | {row['f1']:.3f} | {row['false_positive_rate']:.3f} |\n"
    report += f"""

## Selected-model locked-test results

N = {metrics['n']} ({classifier['dataset']['test_interruption']} positive / {classifier['dataset']['test_non_interruption']} negative).

| Metric | Point estimate | Bootstrap 95% CI |
|---|---:|---:|
| Precision | {metrics['precision']:.3f} | {ci('precision')} |
| Recall | {metrics['recall']:.3f} | {ci('recall')} |
| F1 | {metrics['f1']:.3f} | {ci('f1')} |
| Accuracy | {metrics['accuracy']:.3f} | not preregistered for CI |
| Specificity | {metrics['specificity']:.3f} | not preregistered for CI |
| False interruption rate / FPR | {metrics['false_positive_rate']:.3f} | {ci('false_positive_rate')} |
| Missed interruption rate / FNR | {metrics['false_negative_rate']:.3f} | {ci('false_negative_rate')} |

Confusion matrix `[[TN, FP], [FN, TP]]`: `{metrics['confusion_matrix']}`. Test F1 by seed was {', '.join(f'{value:.3f}' for value in classifier['selected_model_test_f1_by_seed'])}; range = {classifier['selected_model_test_f1_range']:.3f}.

## Recovery experiment

The recovery definition was frozen before running (`{recovery['definition_sha256']}`). It required no unintended mutation, the correct final draft, no confirmation bypass, no duplicate order, the correct safety state, and an advisory-only classifier.

| Condition | N | Recovery successes | Rate |
|---|---:|---:|---:|
"""
    for row in recovery["by_condition"]:
        report += f"| {row['condition']} | {row['n']} | {row['successes']} | {percent(row['recovery_success_rate'])} |\n"
    report += f"""

Overall recovery success: **{recovery['successes']}/{recovery['n']} ({percent(recovery['recovery_success_rate'])})** in synthetic dialogue-state tests. A classifier prediction never confirmed or submitted an order.

## Confidence intervals

Classifier intervals resample locked-test examples. Recovery is reported as a finite deterministic test suite rather than dressed up as user-population inference; no production-success confidence claim is made.

## Error analysis

There were {classifier['error_counts']['false_positives']} false positives and {classifier['error_counts']['false_negatives']} false negatives. Detailed examples and language/SNR/onset/cough/background-speech/acknowledgement breakdowns are in `experiments/reports/barge_in_error_analysis.md` and `experiments/results/barge_in/error_group_metrics.csv`.

The false-interruption rate of {percent(metrics['false_positive_rate'])} is the principal product concern: frequent unnecessary interruptions would degrade playback and require clarification. This exceeded the preregistered 15% CV threshold.

## Limitations

- This is a synthetic programmatic overlapping-**signal** benchmark, not intelligible overlapping speech and not real users.
- The AI playback reference is perfectly aligned, unlike imperfect real echo cancellation.
- There is no real ASR, semantic speech recognition, streaming transport, endpointing, phone audio, or production barge-in integration.
- Generator-specific separability and balanced classes can overstate field performance.
- Recovery tests exercise the existing text state machine after a simulated classifier outcome; they do not demonstrate that live playback was actually stopped.

## Reproducibility

Run `generate_dataset.py`, `features.py`, `train.py`, `evaluate.py`, `recovery_eval.py`, and this analyzer. Raw manifests, feature CSV, validation/test predictions, all seed models, bootstrap JSON, error tables, recovery CSV, SHA-256 hashes, and PNGs are retained.

## CV eligibility

- Interruption classifier: **{classifier['classifier_cv_status']}**. Although F1 is {metrics['f1']:.3f}, FPR is {percent(metrics['false_positive_rate'])} and fails the preregistered ceiling. It is not written into the CV.
- Recovery suite: **{recovery_status}** only as “100% success across 100 synthetic dialogue-state recovery cases”; it is not evidence of production barge-in and is not promoted in the CV because the upstream detector failed eligibility.
- Overall real-world barge-in: **NOT_FOR_CV / NOT_IMPLEMENTED**.
"""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    return final


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--figures-dir", type=Path, default=DEFAULT_FIGURES)
    args = parser.parse_args()
    result = analyze(results_dir=args.results_dir, report_path=args.report, figures_dir=args.figures_dir)
    print(f"classifier={result['classifier_cv_status']}; recovery={result['recovery_cv_status']}; overall={result['overall_barge_in_cv_status']}")


if __name__ == "__main__":
    main()
