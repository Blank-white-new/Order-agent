from __future__ import annotations

from app.domain.enums import DecisionClass
from app.domain.safety import ConfidenceMetadata, SafetyEvaluationContext


def _evaluate(phase3, session, confidence, signals=()):
    phase3.session_store.get(session)
    return phase3.safety_audit_service.evaluate_and_record(
        session_key=session,
        context=SafetyEvaluationContext(
            signals=frozenset(signals),
            confidence=ConfidenceMetadata(overall_confidence=confidence),
        ),
    )


def test_low_confidence_counter_persists_and_isolated_by_session(phase3):
    first = _evaluate(phase3, "low-a", 0.2)
    second = _evaluate(phase3, "low-a", 0.2)
    other = _evaluate(phase3, "low-b", 0.2)
    assert first.decision.classification == DecisionClass.CONFIRM
    assert second.decision.classification == DecisionClass.HANDOFF
    assert second.counters.consecutive_low_confidence == 2
    assert other.decision.classification == DecisionClass.CONFIRM
    assert other.counters.consecutive_low_confidence == 1


def test_successful_high_confidence_turn_resets_low_counter(phase3):
    _evaluate(phase3, "low-reset", 0.2)
    reset = _evaluate(phase3, "low-reset", 0.95, ("UNDERSTOOD",))
    next_low = _evaluate(phase3, "low-reset", 0.2)
    assert reset.counters.consecutive_low_confidence == 0
    assert next_low.counters.consecutive_low_confidence == 1
    assert next_low.decision.classification == DecisionClass.CONFIRM


def test_repeated_corrections_persist_and_handoff(phase3):
    first = _evaluate(phase3, "corrections", 0.9, ("CORRECTION",))
    second = _evaluate(phase3, "corrections", 0.9, ("CORRECTION",))
    assert first.counters.consecutive_corrections == 1
    assert second.counters.consecutive_corrections == 2
    assert second.decision.reason_code == "REPEATED_MISUNDERSTANDING"
