from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict

import numpy as np

from experiments.barge_in.evaluate import bootstrap_metric_cis
from experiments.barge_in.features import FEATURE_NAMES, extract_features
from experiments.barge_in.generate_dataset import synthesize_example
from experiments.barge_in.models import classification_metrics
from experiments.common.io import read_csv, read_jsonl
from experiments.common.metadata import ROOT


DATASET = ROOT / "experiments" / "datasets" / "barge_in_synthetic.jsonl"
RESULTS = ROOT / "experiments" / "results" / "barge_in"


def test_group_split_has_no_template_leakage() -> None:
    rows = read_jsonl(DATASET)
    groups: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        groups[row["split"]].add(row["template_group_id"])
    assert not groups["train"] & groups["validation"]
    assert not groups["train"] & groups["test"]
    assert not groups["validation"] & groups["test"]


def test_split_class_language_and_category_balance() -> None:
    rows = read_jsonl(DATASET)
    assert Counter(row["split"] for row in rows) == {"train": 1120, "validation": 240, "test": 240}
    for split, expected_per_class, expected_per_locale in (("train", 560, 280), ("validation", 120, 60), ("test", 120, 60)):
        subset = [row for row in rows if row["split"] == split]
        assert set(Counter(row["label"] for row in subset).values()) == {expected_per_class}
        assert set(Counter(row["locale"] for row in subset).values()) == {expected_per_locale}
        category_counts = Counter((row["label"], row["event_category"]) for row in subset)
        assert len(set(category_counts.values())) == 1


def test_features_are_deterministic_and_exclude_generator_fields() -> None:
    row = read_jsonl(DATASET)[0]
    mixed_a, ai_a, _ = synthesize_example(row)
    mixed_b, ai_b, _ = synthesize_example(row)
    assert np.array_equal(mixed_a, mixed_b)
    assert np.array_equal(ai_a, ai_b)
    assert extract_features(mixed_a, ai_a) == extract_features(mixed_b, ai_b)
    forbidden = {"label", "locale", "event_category", "onset_pct", "target_snr_db", "template_group_id", "semantic_content"}
    assert not forbidden & set(FEATURE_NAMES)


def test_confusion_matrix_and_rates() -> None:
    metrics = classification_metrics(np.array([0, 0, 1, 1]), np.array([0, 1, 0, 1]))
    assert metrics["confusion_matrix"] == [[1, 1], [1, 1]]
    assert metrics["precision"] == metrics["recall"] == metrics["f1"] == 0.5
    assert metrics["false_positive_rate"] == metrics["false_negative_rate"] == 0.5


def test_bootstrap_is_seeded_and_contains_point_estimate() -> None:
    truth = np.array([0, 0, 0, 1, 1, 1])
    prediction = np.array([0, 1, 0, 1, 0, 1])
    first = bootstrap_metric_cis(truth, prediction, seed=42)
    second = bootstrap_metric_cis(truth, prediction, seed=42)
    assert first == second
    for payload in first.values():
        assert payload["lower"] <= payload["estimate"] <= payload["upper"]
        assert payload["resamples"] == 10_000


def test_recovery_definition_and_classifier_never_confirm_order() -> None:
    definition = json.loads((ROOT / "experiments" / "barge_in" / "recovery_definition.json").read_text(encoding="utf-8"))
    assert set(definition["conditions"]) == {"TP", "FP", "FN", "TN"}
    assert definition["cases_per_condition"] == 25
    assert "no_confirmation_bypass" in definition["success_requires"]
    rows = read_csv(RESULTS / "recovery_raw.csv")
    assert len(rows) == 100
    assert all(row["controller_action"] not in {"CONFIRM_ORDER", "SUBMIT_ORDER"} for row in rows)
    assert all(row["recovery_success"] == "True" for row in rows)
    assert all(row["database_order_count"] == "0" for row in rows)


def test_failed_pilot_is_retained_and_final_classifier_status_is_audited() -> None:
    pilot = RESULTS / "pilot_unbalanced_split"
    assert (pilot / "barge_in_synthetic.jsonl").exists()
    assert (pilot / "validation_predictions.csv").exists()
    analysis = json.loads((RESULTS / "classifier_analysis.json").read_text(encoding="utf-8"))
    assert analysis["classifier_cv_status"] == "NOT_FOR_CV"
    assert analysis["selected_test_metrics"]["false_positive_rate"] > 0.15
