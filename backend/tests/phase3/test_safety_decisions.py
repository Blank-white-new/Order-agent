from __future__ import annotations

import pytest

from app.domain.enums import DecisionClass, HandoffReasonCode, RefusalReasonCode
from app.domain.safety import ConfidenceMetadata, SafetyCounters, SafetyEvaluationContext
from app.services.safety_decision_service import SafetyDecisionService


ALL_HANDOFF_REASONS = [reason.value for reason in HandoffReasonCode]


@pytest.mark.parametrize("reason", ALL_HANDOFF_REASONS)
def test_all_stable_handoff_reasons_are_enforced(reason):
    decision = SafetyDecisionService().evaluate(
        SafetyEvaluationContext(signals=frozenset({reason}), deterministic_input=True)
    )
    assert decision.classification == DecisionClass.HANDOFF
    assert decision.reason_code == reason
    assert "SUBMIT_TO_MERCHANT" in decision.blocked_actions


@pytest.mark.parametrize("reason", [reason.value for reason in RefusalReasonCode])
def test_all_refusal_reasons_block_side_effects(reason):
    decision = SafetyDecisionService().evaluate(
        SafetyEvaluationContext(
            signals=frozenset({reason}),
            requested_action="MODIFY_ORDER",
            deterministic_input=True,
        )
    )
    assert decision.classification == DecisionClass.REFUSE
    assert decision.reason_code == reason
    assert "MODIFY_ORDER" in decision.blocked_actions


def test_priority_is_explicit_refuse_then_handoff_then_confirm_then_draft():
    service = SafetyDecisionService()
    refused = service.evaluate(
        SafetyEvaluationContext(
            signals=frozenset({"CARD_DATA_STORAGE", "SEVERE_ALLERGY", "FINAL_ORDER"}),
            deterministic_input=True,
        )
    )
    handed_off = service.evaluate(
        SafetyEvaluationContext(
            signals=frozenset({"SEVERE_ALLERGY", "FINAL_ORDER"}), deterministic_input=True
        )
    )
    confirmed = service.evaluate(
        SafetyEvaluationContext(signals=frozenset({"FINAL_ORDER"}), deterministic_input=True)
    )
    drafted = service.evaluate(SafetyEvaluationContext(deterministic_input=True))
    assert [refused.classification, handed_off.classification, confirmed.classification, drafted.classification] == [
        DecisionClass.REFUSE,
        DecisionClass.HANDOFF,
        DecisionClass.CONFIRM,
        DecisionClass.AUTO_DRAFT,
    ]


def test_high_confidence_never_bypasses_allergy_or_final_confirmation():
    confidence = ConfidenceMetadata(overall_confidence=1.0)
    service = SafetyDecisionService()
    allergy = service.evaluate(
        SafetyEvaluationContext(
            signals=frozenset({"SEVERE_ALLERGY"}), confidence=confidence, deterministic_input=True
        )
    )
    final = service.evaluate(
        SafetyEvaluationContext(
            signals=frozenset({"FINAL_ORDER"}), confidence=confidence, deterministic_input=True
        )
    )
    assert allergy.classification == DecisionClass.HANDOFF
    assert final.classification == DecisionClass.CONFIRM


def test_missing_and_contradictory_confidence_are_conservative():
    service = SafetyDecisionService()
    missing = service.evaluate(SafetyEvaluationContext())
    contradictory = service.evaluate(
        SafetyEvaluationContext(
            confidence=ConfidenceMetadata(
                item_confidence=0.9,
                overall_confidence=0.9,
                contradictory_fields=("item_confidence",),
            )
        )
    )
    assert missing.classification == DecisionClass.CONFIRM
    assert missing.required_confirmations == ("intent",)
    assert contradictory.classification == DecisionClass.CONFIRM
    assert "item" in contradictory.required_confirmations


def test_first_low_confidence_confirms_and_continuous_low_hands_off():
    service = SafetyDecisionService()
    first = service.evaluate(
        SafetyEvaluationContext(
            confidence=ConfidenceMetadata(overall_confidence=0.2),
            counters=SafetyCounters(consecutive_low_confidence=1),
        )
    )
    repeated = service.evaluate(
        SafetyEvaluationContext(
            confidence=ConfidenceMetadata(overall_confidence=0.2),
            counters=SafetyCounters(consecutive_low_confidence=2),
        )
    )
    assert first.classification == DecisionClass.CONFIRM
    assert repeated.classification == DecisionClass.HANDOFF
    assert repeated.reason_code == "REPEATED_MISUNDERSTANDING"


def test_confidence_bounds_are_validated():
    with pytest.raises(ValueError):
        ConfidenceMetadata(overall_confidence=1.1)
