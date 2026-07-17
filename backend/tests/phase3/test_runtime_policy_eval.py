from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.run_phase1_runtime_policy_eval import ROOT, run


def test_phase1_runtime_policy_metadata_maps_at_100_percent_without_claiming_language_parser():
    result = run(ROOT / "evaluation" / "phase1_scenarios.jsonl")
    assert result.total_scenarios == 140
    assert result.policy_runnable_scenarios == 140
    assert result.classification_matches == 140
    assert result.handoff_reason_matches == result.handoff_reason_scenarios
    assert result.refusal_matches == result.refusal_scenarios
    assert result.language_parsing_not_implemented == 105
    assert result.erroneous_auto_submit == 0
    assert result.confirmation_bypass == 0
    assert result.serious_allergy_omission == 0
    assert result.cross_tenant_handoff_leak == 0
    assert result.fake_merchant_acceptance == 0
