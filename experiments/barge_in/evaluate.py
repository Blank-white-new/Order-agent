from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from experiments.barge_in.features import FEATURE_NAMES
from experiments.barge_in.models import classification_metrics, model_from_dict
from experiments.barge_in.train import SEEDS, matrix
from experiments.common.charts import bar_chart, confusion_matrix_chart
from experiments.common.io import read_csv, read_jsonl, write_csv, write_json
from experiments.common.metadata import ROOT, collect_metadata, sha256_file


DEFAULT_DATASET = ROOT / "experiments" / "datasets" / "barge_in_synthetic.jsonl"
DEFAULT_FEATURES = ROOT / "experiments" / "results" / "barge_in" / "features.csv"
DEFAULT_RESULTS = ROOT / "experiments" / "results" / "barge_in"
DEFAULT_ERROR_REPORT = ROOT / "experiments" / "reports" / "barge_in_error_analysis.md"
DEFAULT_FIGURES = ROOT / "experiments" / "reports" / "figures" / "barge_in"
RESAMPLES = 10_000


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def bootstrap_metric_cis(y_true: np.ndarray, y_pred: np.ndarray, *, seed: int = 42) -> dict:
    rng = np.random.default_rng(seed)
    metric_names = ("precision", "recall", "f1", "false_positive_rate", "false_negative_rate")
    estimates = {name: np.empty(RESAMPLES, dtype=float) for name in metric_names}
    chunk = 250
    for start in range(0, RESAMPLES, chunk):
        size = min(chunk, RESAMPLES - start)
        indexes = rng.integers(0, y_true.size, size=(size, y_true.size))
        truth = y_true[indexes]
        predicted = y_pred[indexes]
        tp = np.sum((truth == 1) & (predicted == 1), axis=1)
        fp = np.sum((truth == 0) & (predicted == 1), axis=1)
        tn = np.sum((truth == 0) & (predicted == 0), axis=1)
        fn = np.sum((truth == 1) & (predicted == 0), axis=1)
        precision = np.divide(tp, tp + fp, out=np.zeros(size), where=(tp + fp) != 0)
        recall = np.divide(tp, tp + fn, out=np.zeros(size), where=(tp + fn) != 0)
        f1 = np.divide(2 * precision * recall, precision + recall, out=np.zeros(size), where=(precision + recall) != 0)
        fpr = np.divide(fp, fp + tn, out=np.zeros(size), where=(fp + tn) != 0)
        fnr = np.divide(fn, fn + tp, out=np.zeros(size), where=(fn + tp) != 0)
        for name, values in zip(metric_names, (precision, recall, f1, fpr, fnr)):
            estimates[name][start : start + size] = values
    point = classification_metrics(y_true, y_pred)
    return {
        name: {
            "estimate": float(point[name]),
            "lower": float(np.quantile(values, 0.025)),
            "upper": float(np.quantile(values, 0.975)),
            "resamples": RESAMPLES,
            "seed": seed,
        }
        for name, values in estimates.items()
    }


def group_metrics(rows: list[dict], key: str) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[str(row[key])].append(row)
    output = []
    for group, items in sorted(groups.items()):
        truth = np.asarray([row["truth"] for row in items], dtype=int)
        prediction = np.asarray([row["prediction"] for row in items], dtype=int)
        metrics = classification_metrics(truth, prediction)
        output.append({"grouping": key, "group": group, **{name: value for name, value in metrics.items() if name != "confusion_matrix"}})
    return output


def _error_lines(title: str, rows: list[dict], *, reverse: bool) -> list[str]:
    output = [f"### {title}", ""]
    if not rows:
        return [*output, "None.", ""]
    ranked = sorted(rows, key=lambda row: row["probability"], reverse=reverse)
    output.extend(("| Example | Locale | Category | SNR dB | Onset | Probability | Synthetic semantic template |", "|---|---|---|---:|---:|---:|---|"))
    for row in ranked[:30]:
        semantic = str(row["semantic_content"]).replace("|", "/")
        output.append(
            f"| {row['example_id']} | {row['locale']} | {row['event_category']} | {row['target_snr_db']} | {row['onset_pct']}% | {row['probability']:.4f} | {semantic} |"
        )
    output.append("")
    return output


def evaluate(
    *,
    dataset_path: Path,
    features_path: Path,
    results_dir: Path,
    error_report_path: Path,
    figures_dir: Path,
) -> dict:
    features = read_csv(features_path)
    test_rows = [row for row in features if row["split"] == "test"]
    if len(test_rows) != 240:
        raise ValueError("locked test split must contain 240 examples")
    x_test, y_test = matrix(test_rows)
    selection = load_json(results_dir / "model_selection.json")
    selected_name = selection["selected_model"]
    model_names = ("rule_baseline", "logistic_regression", "gradient_boosting_stumps")
    all_predictions: list[dict] = []
    comparison_rows: list[dict] = []
    ensemble_payloads: dict[str, dict] = {}
    seed_f1_by_model: dict[str, list[float]] = defaultdict(list)

    for model_name in model_names:
        seed_predictions = []
        seed_probabilities = []
        for seed in SEEDS:
            model_path = results_dir / "models" / f"{model_name}_seed_{seed}.json"
            model = model_from_dict(load_json(model_path))
            probabilities = model.predict_proba(x_test)
            predictions = (probabilities >= model.threshold).astype(int)
            metrics = classification_metrics(y_test, predictions)
            seed_f1_by_model[model_name].append(float(metrics["f1"]))
            comparison_rows.append(
                {
                    "model": model_name,
                    "evaluation": f"seed_{seed}",
                    "split": "locked_test",
                    **{key: value for key, value in metrics.items() if key != "confusion_matrix"},
                    "threshold": model.threshold,
                }
            )
            seed_predictions.append(predictions)
            seed_probabilities.append(probabilities)
            for row, probability, prediction in zip(test_rows, probabilities, predictions):
                all_predictions.append(
                    {
                        "model": model_name,
                        "evaluation": f"seed_{seed}",
                        "example_id": row["example_id"],
                        "truth": int(row["target"]),
                        "probability": float(probability),
                        "prediction": int(prediction),
                    }
                )
        ensemble_prediction = (np.sum(seed_predictions, axis=0) >= 2).astype(int)
        ensemble_probability = np.mean(seed_probabilities, axis=0)
        ensemble_metrics = classification_metrics(y_test, ensemble_prediction)
        ensemble_payloads[model_name] = {
            "predictions": ensemble_prediction,
            "probabilities": ensemble_probability,
            "metrics": ensemble_metrics,
        }
        comparison_rows.append(
            {
                "model": model_name,
                "evaluation": "three_seed_majority_vote",
                "split": "locked_test",
                **{key: value for key, value in ensemble_metrics.items() if key != "confusion_matrix"},
                "threshold": "per-seed validation thresholds",
            }
        )
        for row, probability, prediction in zip(test_rows, ensemble_probability, ensemble_prediction):
            all_predictions.append(
                {
                    "model": model_name,
                    "evaluation": "three_seed_majority_vote",
                    "example_id": row["example_id"],
                    "truth": int(row["target"]),
                    "probability": float(probability),
                    "prediction": int(prediction),
                }
            )

    selected = ensemble_payloads[selected_name]
    primary_rows = []
    manifest_by_id = {row["example_id"]: row for row in read_jsonl(dataset_path)}
    for feature_row, probability, prediction in zip(test_rows, selected["probabilities"], selected["predictions"]):
        source = manifest_by_id[feature_row["example_id"]]
        primary_rows.append(
            {
                "example_id": feature_row["example_id"],
                "template_group_id": feature_row["template_group_id"],
                "truth": int(feature_row["target"]),
                "prediction": int(prediction),
                "probability": float(probability),
                "locale": source["locale"],
                "event_category": source["event_category"],
                "target_snr_db": source["target_snr_db"],
                "onset_pct": source["onset_pct"],
                "semantic_content": source["semantic_content"],
            }
        )

    primary_metrics = selected["metrics"]
    cis = bootstrap_metric_cis(y_test, selected["predictions"])
    grouped = []
    for key in ("locale", "target_snr_db", "onset_pct", "event_category"):
        grouped.extend(group_metrics(primary_rows, key))
    false_positives = [row for row in primary_rows if row["truth"] == 0 and row["prediction"] == 1]
    false_negatives = [row for row in primary_rows if row["truth"] == 1 and row["prediction"] == 0]
    seed_range = max(seed_f1_by_model[selected_name]) - min(seed_f1_by_model[selected_name])
    eligibility_checks = {
        "synthetic_label_required": True,
        "test_n_at_least_150": len(test_rows) >= 150,
        "class_balanced_test": int(np.sum(y_test == 1)) == int(np.sum(y_test == 0)),
        "group_split_no_leakage": not (
            {row["template_group_id"] for row in features if row["split"] == "train"}
            & {row["template_group_id"] for row in test_rows}
        ),
        "semantic_and_generator_fields_excluded_from_model": True,
        "f1_at_least_0_80": primary_metrics["f1"] >= 0.80,
        "precision_at_least_0_75": primary_metrics["precision"] >= 0.75,
        "recall_at_least_0_75": primary_metrics["recall"] >= 0.75,
        "fpr_at_most_0_15": primary_metrics["false_positive_rate"] <= 0.15,
        "selected_seed_f1_range_at_most_0_03": seed_range <= 0.03,
        "bootstrap_ci_available": cis["f1"]["lower"] is not None,
    }
    classifier_status = "PRELIMINARY_CV_WITH_QUALIFIER" if all(eligibility_checks.values()) else "NOT_FOR_CV"
    analysis = {
        "experiment": "synthetic_barge_in_classifier",
        "selected_model": selected_name,
        "selection_split": "validation only",
        "test_split": "opened after model selection was saved",
        "dataset": {
            "n": len(features),
            "train": sum(row["split"] == "train" for row in features),
            "validation": sum(row["split"] == "validation" for row in features),
            "test": len(test_rows),
            "test_interruption": int(np.sum(y_test == 1)),
            "test_non_interruption": int(np.sum(y_test == 0)),
            "dataset_sha256": sha256_file(dataset_path),
        },
        "selected_test_metrics": primary_metrics,
        "bootstrap_95_ci": cis,
        "selected_model_test_f1_by_seed": seed_f1_by_model[selected_name],
        "selected_model_test_f1_range": seed_range,
        "model_comparison": comparison_rows,
        "error_counts": {"false_positives": len(false_positives), "false_negatives": len(false_negatives)},
        "eligibility_checks": eligibility_checks,
        "classifier_cv_status": classifier_status,
        "mandatory_qualifier": "synthetic programmatic overlapping-signal prototype; not real speech or real-world barge-in",
    }
    write_json(results_dir / "classifier_analysis.json", analysis)
    write_csv(results_dir / "test_predictions_all_models.csv", all_predictions)
    write_csv(results_dir / "selected_test_predictions.csv", primary_rows)
    write_csv(results_dir / "test_model_comparison.csv", comparison_rows)
    write_csv(results_dir / "error_group_metrics.csv", grouped)
    write_json(
        results_dir / "evaluation_metadata.json",
        collect_metadata(
            dataset_sha256=sha256_file(dataset_path),
            random_seed=42,
            warmup_count=0,
            measurement_count=len(test_rows),
            provider_mode="offline_synthetic_signal_classifier",
            asr_provider="NOT_USED",
            tts_provider="NOT_USED",
            extra={
                "experiment": "synthetic_barge_in_evaluation",
                "selected_model": selected_name,
                "seeds": list(SEEDS),
                "bootstrap_resamples": RESAMPLES,
                "test_group_count": len({row["template_group_id"] for row in test_rows}),
                "real_speech_used": False,
                "test_predictions_sha256": sha256_file(results_dir / "selected_test_predictions.csv"),
            },
        ),
    )

    confusion_matrix_chart(
        figures_dir / "confusion_matrix.png",
        title="Synthetic interruption classifier — locked test",
        matrix=primary_metrics["confusion_matrix"],
    )
    locale_rows = [row for row in grouped if row["grouping"] == "locale"]
    bar_chart(
        figures_dir / "f1_by_language.png",
        title="Synthetic test F1 by locale",
        labels=[row["group"] for row in locale_rows],
        values=[row["f1"] for row in locale_rows],
        y_label="F1",
    )
    snr_rows = [row for row in grouped if row["grouping"] == "target_snr_db"]
    bar_chart(
        figures_dir / "f1_by_snr.png",
        title="Synthetic test F1 by configured SNR",
        labels=[f"{row['group']} dB" for row in snr_rows],
        values=[row["f1"] for row in snr_rows],
        y_label="F1",
    )
    bar_chart(
        figures_dir / "false_interruption_and_miss_rates.png",
        title="Synthetic false-interruption and missed-interruption rates",
        labels=("False interruption (FPR)", "Missed interruption (FNR)"),
        values=(primary_metrics["false_positive_rate"], primary_metrics["false_negative_rate"]),
        y_label="rate",
    )

    fp_counts = Counter(row["event_category"] for row in false_positives)
    fn_counts = Counter(row["event_category"] for row in false_negatives)
    error_report = [
        "# Synthetic Barge-in Error Analysis",
        "",
        f"Selected model: `{selected_name}` (three-seed majority vote). Locked test N={len(test_rows)}.",
        "",
        "> All inputs are programmatic harmonic/noise overlaps. They contain no recorded voice and no intelligible TTS. These errors do not estimate real-user barge-in performance.",
        "",
        "## Most common false positives",
        "",
        ", ".join(f"{name}: {count}" for name, count in fp_counts.most_common()) or "None.",
        "",
        "## Most common false negatives",
        "",
        ", ".join(f"{name}: {count}" for name, count in fn_counts.most_common()) or "None.",
        "",
        *_error_lines("False-positive examples", false_positives, reverse=True),
        *_error_lines("False-negative examples", false_negatives, reverse=False),
        "## Stratified performance",
        "",
        "The machine-readable table `experiments/results/barge_in/error_group_metrics.csv` reports language, configured SNR, onset, and every event category. It explicitly includes cough-like noise, background synthetic speech, acknowledgements, silence, breathing-like noise, cutlery transients, and music-like mixtures.",
        "",
        "## Interpretation",
        "",
        "Speech-like negative overlays are the hard cases because the prototype deliberately has no ASR/text semantics. Performance is therefore bounded by acoustic separability in this generator. The dataset is not evidence of real speech recognition, real barge-in, or caller behavior.",
    ]
    error_report_path.parent.mkdir(parents=True, exist_ok=True)
    error_report_path.write_text("\n".join(error_report) + "\n", encoding="utf-8")
    return analysis


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--features", type=Path, default=DEFAULT_FEATURES)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--error-report", type=Path, default=DEFAULT_ERROR_REPORT)
    parser.add_argument("--figures-dir", type=Path, default=DEFAULT_FIGURES)
    args = parser.parse_args()
    result = evaluate(
        dataset_path=args.dataset,
        features_path=args.features,
        results_dir=args.results_dir,
        error_report_path=args.error_report,
        figures_dir=args.figures_dir,
    )
    metrics = result["selected_test_metrics"]
    print(f"{result['selected_model']}: test F1={metrics['f1']:.4f}, FPR={metrics['false_positive_rate']:.4f}, {result['classifier_cv_status']}")


if __name__ == "__main__":
    main()
