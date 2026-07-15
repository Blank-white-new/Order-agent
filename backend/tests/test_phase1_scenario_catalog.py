from __future__ import annotations

import json

from scripts.validate_phase1_scenarios import (
    DEFAULT_CATALOG,
    DEFAULT_SCHEMA,
    MIN_PER_LOCALE,
    MIN_SCENARIOS,
    validate_catalog,
)


def test_phase1_scenario_catalog_passes_policy_validation():
    result = validate_catalog()

    assert result.errors == []
    assert result.ok is True
    assert result.summary["total"] >= MIN_SCENARIOS
    assert all(count >= MIN_PER_LOCALE for count in result.summary["locales"].values())
    assert result.summary["high_risk_isolated"] == 0
    assert result.summary["blocking_metrics_isolated"] == 0


def test_phase1_catalog_and_schema_are_utf8_json(tmp_path):
    schema = json.loads(DEFAULT_SCHEMA.read_text(encoding="utf-8"))
    lines = DEFAULT_CATALOG.read_text(encoding="utf-8").splitlines()

    assert schema["properties"]["expected_classification"]["enum"] == [
        "AUTO_DRAFT",
        "CONFIRM",
        "HANDOFF",
        "REFUSE",
    ]
    assert len(lines) >= MIN_SCENARIOS
    assert all(isinstance(json.loads(line), dict) for line in lines)


def test_phase1_validator_rejects_forbidden_auto_submit(tmp_path):
    rows = [json.loads(line) for line in DEFAULT_CATALOG.read_text(encoding="utf-8").splitlines()]
    rows[0]["expected_classification"] = "AUTO_SUBMIT"
    broken_catalog = tmp_path / "broken.jsonl"
    broken_catalog.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )

    result = validate_catalog(catalog_path=broken_catalog)

    assert result.ok is False
    assert any("AUTO_SUBMIT" in error for error in result.errors)
