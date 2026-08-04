from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from time import perf_counter_ns

import numpy as np

from experiments.barge_in.features import FEATURE_NAMES
from experiments.barge_in.models import (
    GradientBoostingStumps,
    LogisticModel,
    RuleModel,
    choose_threshold,
    classification_metrics,
)
from experiments.common.io import read_csv, write_csv, write_json
from experiments.common.metadata import ROOT, collect_metadata, sha256_file


DEFAULT_FEATURES = ROOT / "experiments" / "results" / "barge_in" / "features.csv"
DEFAULT_RESULTS = ROOT / "experiments" / "results" / "barge_in"
SEEDS = (42, 43, 44)


def matrix(rows: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    return (
        np.asarray([[float(row[name]) for name in FEATURE_NAMES] for row in rows], dtype=float),
        np.asarray([int(row["target"]) for row in rows], dtype=int),
    )


def run_training(*, features_path: Path, results_dir: Path) -> dict:
    rows = read_csv(features_path)
    train_rows = [row for row in rows if row["split"] == "train"]
    validation_rows = [row for row in rows if row["split"] == "validation"]
    test_rows = [row for row in rows if row["split"] == "test"]
    train_groups = {row["template_group_id"] for row in train_rows}
    validation_groups = {row["template_group_id"] for row in validation_rows}
    test_groups = {row["template_group_id"] for row in test_rows}
    if train_groups & validation_groups or train_groups & test_groups or validation_groups & test_groups:
        raise ValueError("template-group leakage across dataset split")
    x_train, y_train = matrix(train_rows)
    x_validation, y_validation = matrix(validation_rows)
    results_dir.mkdir(parents=True, exist_ok=True)

    training_rows: list[dict] = []
    validation_predictions: list[dict] = []
    validation_by_model: dict[str, list[float]] = {}
    for seed in SEEDS:
        models = (
            RuleModel(),
            LogisticModel.fit(x_train, y_train, seed=seed),
            GradientBoostingStumps.fit(x_train, y_train, seed=seed),
        )
        for model in models:
            probabilities = model.predict_proba(x_validation)
            if model.name != "rule_baseline":
                model.threshold, _ = choose_threshold(y_validation, probabilities)
            predictions = probabilities >= model.threshold
            metrics = classification_metrics(y_validation, predictions)
            started = perf_counter_ns()
            for _ in range(100):
                model.predict_proba(x_validation)
            inference_ns_per_sample = (perf_counter_ns() - started) / (100 * len(validation_rows))
            payload = model.serializable()
            payload.update({"seed": seed, "feature_names": list(FEATURE_NAMES), "selection_split": "validation"})
            model_path = results_dir / "models" / f"{model.name}_seed_{seed}.json"
            write_json(model_path, payload)
            training_rows.append(
                {
                    "model": model.name,
                    "seed": seed,
                    "split": "validation",
                    **{key: value for key, value in metrics.items() if key != "confusion_matrix"},
                    "threshold": model.threshold,
                    "inference_ns_per_sample": inference_ns_per_sample,
                    "model_path": str(model_path.relative_to(ROOT)),
                    "model_sha256": sha256_file(model_path),
                }
            )
            validation_by_model.setdefault(model.name, []).append(float(metrics["f1"]))
            for row, probability, prediction in zip(validation_rows, probabilities, predictions):
                validation_predictions.append(
                    {
                        "model": model.name,
                        "seed": seed,
                        "example_id": row["example_id"],
                        "template_group_id": row["template_group_id"],
                        "truth": int(row["target"]),
                        "probability": float(probability),
                        "prediction": int(prediction),
                    }
                )

    complexity_order = {"rule_baseline": 0, "logistic_regression": 1, "gradient_boosting_stumps": 2}
    comparison = [
        {
            "model": name,
            "validation_mean_f1": statistics.fmean(values),
            "validation_min_f1": min(values),
            "validation_max_f1": max(values),
            "seeds": list(SEEDS),
        }
        for name, values in validation_by_model.items()
    ]
    selected = max(comparison, key=lambda row: (row["validation_mean_f1"], -complexity_order[row["model"]]))
    selection = {
        "selected_model": selected["model"],
        "selection_rule": "highest mean validation F1 across seeds; ties prefer lower complexity",
        "test_labels_accessed_during_selection": False,
        "validation_comparison": sorted(comparison, key=lambda row: complexity_order[row["model"]]),
        "model_rationale": {
            "rule_baseline": "transparent and near-zero inference cost, but limited nonlinear separation",
            "logistic_regression": "interpretable linear boundary suitable for 1,120 training samples",
            "gradient_boosting_stumps": "bounded nonlinear capability without a high-capacity deep model; group split and seed stability monitor overfitting",
        },
        "split_counts": {"train": len(train_rows), "validation": len(validation_rows), "test_locked": len(test_rows)},
        "group_counts": {"train": len(train_groups), "validation": len(validation_groups), "test_locked": len(test_groups)},
    }
    write_json(results_dir / "model_selection.json", selection)
    write_csv(results_dir / "training_metrics.csv", training_rows)
    write_csv(results_dir / "validation_predictions.csv", validation_predictions)
    metadata = collect_metadata(
        dataset_sha256=sha256_file(features_path),
        random_seed=42,
        warmup_count=0,
        measurement_count=len(train_rows) + len(validation_rows),
        provider_mode="offline_synthetic_signal_classifier",
        asr_provider="NOT_USED",
        tts_provider="NOT_USED",
        extra={
            "experiment": "synthetic_barge_in_training",
            "seeds": list(SEEDS),
            "feature_names": list(FEATURE_NAMES),
            "expected_text_used_as_feature": False,
            "test_split_accessed_for_model_selection": False,
            "features_csv_sha256": sha256_file(features_path),
        },
    )
    write_json(results_dir / "training_metadata.json", metadata)
    return selection


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", type=Path, default=DEFAULT_FEATURES)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS)
    args = parser.parse_args()
    print(json.dumps(run_training(features_path=args.features, results_dir=args.results_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
