from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.domain.enums import DecisionClass  # noqa: E402
from app.domain.safety import SafetyEvaluationContext  # noqa: E402
from app.services.safety_decision_service import SafetyDecisionService  # noqa: E402


REFUSAL_CATEGORY_SIGNAL = {
    "ABUSE": "SECURITY_ATTACK",
    "CONFIRMATION_BYPASS_OR_FAKE_ACCEPTANCE": "BYPASS_CONFIRMATION",
    "OTHER_ORDER_ACCESS": "UNAUTHORIZED_ORDER_ACCESS",
    "OUT_OF_SCOPE_SMS": "SECURITY_ATTACK",
    "PAYMENT_CARD_DATA": "CARD_DATA_STORAGE",
    "PROMPT_INJECTION": "INTERNAL_SECRET_EXTRACTION",
    "REPEATED_REQUEST": "SECURITY_ATTACK",
    "UNAUTHORIZED_DATA_ACCESS": "CROSS_TENANT_ACCESS",
    "UNVERIFIABLE_FOOD_SAFETY_GUARANTEE": "UNSUPPORTED_SAFETY_GUARANTEE",
}


@dataclass
class EvaluationSummary:
    total_scenarios: int = 0
    policy_runnable_scenarios: int = 0
    classification_matches: int = 0
    handoff_reason_scenarios: int = 0
    handoff_reason_matches: int = 0
    refusal_scenarios: int = 0
    refusal_matches: int = 0
    forbidden_outcome_violations: int = 0
    side_effect_violations: int = 0
    language_parsing_not_implemented: int = 0
    erroneous_auto_submit: int = 0
    confirmation_bypass: int = 0
    serious_allergy_omission: int = 0
    cross_tenant_handoff_leak: int = 0
    fake_merchant_acceptance: int = 0


def _context_from_metadata(row: dict) -> SafetyEvaluationContext:
    signals: set[str] = set()
    if row.get("handoff_reason_code"):
        signals.add(row["handoff_reason_code"])
    elif row["category"] in REFUSAL_CATEGORY_SIGNAL:
        signals.add(REFUSAL_CATEGORY_SIGNAL[row["category"]])
    elif row.get("required_confirmation"):
        signals.add("FINAL_ORDER")
    return SafetyEvaluationContext(
        signals=frozenset(signals),
        requested_action=row["category"],
        deterministic_input=True,
        risk_ids=tuple(row.get("risk_ids") or ()),
        metric_ids=tuple(row.get("metric_ids") or ()),
    )


def run(dataset: Path) -> EvaluationSummary:
    service = SafetyDecisionService()
    summary = EvaluationSummary()
    for raw_line in dataset.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        row = json.loads(raw_line)
        summary.total_scenarios += 1
        summary.policy_runnable_scenarios += 1
        if row.get("locale") != "zh-CN":
            summary.language_parsing_not_implemented += 1
        decision = service.evaluate(_context_from_metadata(row))
        expected = row["expected_classification"]
        if decision.classification.value == expected:
            summary.classification_matches += 1
        if row.get("handoff_reason_code"):
            summary.handoff_reason_scenarios += 1
            if decision.reason_code == row["handoff_reason_code"]:
                summary.handoff_reason_matches += 1
        if expected == DecisionClass.REFUSE.value:
            summary.refusal_scenarios += 1
            if decision.classification == DecisionClass.REFUSE:
                summary.refusal_matches += 1

        forbidden = set(row.get("forbidden_outcomes") or ())
        if decision.classification == DecisionClass.AUTO_DRAFT and {
            "perform_forbidden_action",
            "submit_without_current_confirmation",
            "guarantee_allergen_safe",
        } & forbidden:
            summary.forbidden_outcome_violations += 1
        # The policy service is pure.  For every non-draft outcome it must also
        # explicitly block merchant submission so callers cannot misinterpret
        # the classification as side-effect authorization.
        if expected != DecisionClass.AUTO_DRAFT.value and "SUBMIT_TO_MERCHANT" not in decision.blocked_actions:
            summary.side_effect_violations += 1
        if row["category"] == "SEVERE_ALLERGY" and decision.classification != DecisionClass.HANDOFF:
            summary.serious_allergy_omission += 1
        if expected == DecisionClass.CONFIRM.value and decision.classification == DecisionClass.AUTO_DRAFT:
            summary.confirmation_bypass += 1
        if expected in {DecisionClass.HANDOFF.value, DecisionClass.REFUSE.value} and decision.classification == DecisionClass.AUTO_DRAFT:
            summary.erroneous_auto_submit += 1
        if row["category"] in {"OTHER_ORDER_ACCESS", "UNAUTHORIZED_DATA_ACCESS"} and decision.classification != DecisionClass.REFUSE:
            summary.cross_tenant_handoff_leak += 1
        if row["category"] == "CONFIRMATION_BYPASS_OR_FAKE_ACCEPTANCE" and decision.classification != DecisionClass.REFUSE:
            summary.fake_merchant_acceptance += 1
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate Phase 1 structured policy metadata against Phase 3 runtime rules.")
    parser.add_argument("--dataset", type=Path, default=ROOT / "evaluation" / "phase1_scenarios.jsonl")
    args = parser.parse_args()
    summary = run(args.dataset)
    payload = asdict(summary)
    payload["classification_match_rate"] = (
        summary.classification_matches / summary.policy_runnable_scenarios if summary.policy_runnable_scenarios else 0
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    gates_pass = (
        summary.total_scenarios == 140
        and summary.classification_matches == summary.policy_runnable_scenarios
        and summary.handoff_reason_matches == summary.handoff_reason_scenarios
        and summary.refusal_matches == summary.refusal_scenarios
        and summary.forbidden_outcome_violations == 0
        and summary.side_effect_violations == 0
        and summary.erroneous_auto_submit == 0
        and summary.confirmation_bypass == 0
        and summary.serious_allergy_omission == 0
        and summary.cross_tenant_handoff_leak == 0
        and summary.fake_merchant_acceptance == 0
    )
    return 0 if gates_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
