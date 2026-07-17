from __future__ import annotations

import pytest
from concurrent.futures import ThreadPoolExecutor

from app.domain.enums import HandoffFailureCode
from app.domain.errors import DomainError
from app.domain.safety import SafetyEvaluationContext
from app.services.handoff_service import ALLOWED_TRANSITIONS
from app.services.handoff_summary_service import HandoffSummaryService


def _request(phase3, session_key="handoff-session", reason="SEVERE_ALLERGY"):
    state = phase3.session_store.get(session_key)
    record = phase3.safety_audit_service.evaluate_and_record(
        session_key=session_key,
        context=SafetyEvaluationContext(signals=frozenset({reason}), deterministic_input=True),
    )
    return phase3.handoff_service.request_handoff(
        session_key=session_key,
        state=state,
        decision=record.decision,
        trace_id=record.trace_id,
    )


def test_request_is_idempotent_and_summary_is_structured_and_redacted(phase3):
    state = phase3.session_store.get("summary-session")
    state.phone = "+852 5555 0101"
    state.official_delivery_address = "Synthetic Tower, 1 Test Road"
    phase3.session_store.set("summary-session", state)
    first = _request(phase3, "summary-session")
    second = _request(phase3, "summary-session")
    assert first["handoffId"] == second["handoffId"]
    assert first["status"] == "PENDING"
    assert first["isSynthetic"] is True
    assert first["simulationNotice"] == "模拟人工接管，不是真实人工"
    serialized = str(first["summary"])
    assert "5555 0101" not in serialized
    assert "Synthetic Tower" not in serialized
    assert first["summary"]["contact"] == {"phoneMasked": "***", "addressMasked": "***"}
    assert first["summary"]["forbiddenActions"]


def test_allowed_state_machine_path_and_resolve_never_marks_merchant_accepted(phase3):
    case = _request(phase3, "state-machine")
    case = phase3.handoff_service.simulate_assign(case["handoffId"], None, None)
    assert case["status"] == "SIMULATED_AGENT_ASSIGNED"
    case = phase3.handoff_service.simulate_connect(case["handoffId"], None, None)
    assert case["status"] == "SIMULATED_AGENT_CONNECTED"
    case = phase3.handoff_service.resolve(
        case["handoffId"], {"resolutionCode": "SIMULATED_REVIEWED", "draftChanged": False}, None, None
    )
    assert case["status"] == "RESOLVED"
    assert case["summary"]["order"]["lifecycleStatus"] != "MERCHANT_ACCEPTED"
    assert "MARK_MERCHANT_ACCEPTED" in case["blockedActions"]


@pytest.mark.parametrize(
    ("operation", "expected_code"),
    [
        ("connect", "INVALID_HANDOFF_TRANSITION"),
        ("resolve", "INVALID_HANDOFF_TRANSITION"),
    ],
)
def test_illegal_state_transitions_are_rejected(phase3, operation, expected_code):
    case = _request(phase3, f"illegal-{operation}")
    with pytest.raises(DomainError) as error:
        if operation == "connect":
            phase3.handoff_service.simulate_connect(case["handoffId"], None, None)
        else:
            phase3.handoff_service.resolve(
                case["handoffId"], {"resolutionCode": "SIMULATED", "draftChanged": False}, None, None
            )
    assert error.value.code == expected_code


@pytest.mark.parametrize("failure", list(HandoffFailureCode))
def test_all_failure_codes_preserve_a_non_submittable_case(phase3, failure):
    case = _request(phase3, f"failure-{failure.value}")
    failed = phase3.handoff_service.simulate_fail(case["handoffId"], failure, None, None)
    assert failed["status"] == "FAILED"
    assert failed["failureCode"] == failure.value
    assert "SUBMIT_TO_MERCHANT" in failed["blockedActions"]


def test_cancel_only_cancels_handoff_not_order(phase3):
    case = _request(phase3, "cancel-handoff", "EXPLICIT_HUMAN_REQUEST")
    cancelled = phase3.handoff_service.cancel(case["handoffId"], None, None)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["failureCode"] == "CASE_CANCELLED"


def test_tenant_scoped_lookup_does_not_disclose_case(phase3):
    case = _request(phase3, "tenant-hidden")
    with pytest.raises(DomainError) as error:
        phase3.handoff_service.get(case["handoffId"], "hk-sim-restaurant-b", "north")
    assert error.value.code == "HANDOFF_NOT_FOUND"


def test_state_machine_matrix_has_no_implicit_or_real_human_state():
    statuses = set(ALLOWED_TRANSITIONS)
    assert "HUMAN_CONNECTED" not in {status.value for status in statuses}
    assert {target for targets in ALLOWED_TRANSITIONS.values() for target in targets} <= statuses
    assert ALLOWED_TRANSITIONS[next(status for status in statuses if status.value == "RESOLVED")] == set()
    assert ALLOWED_TRANSITIONS[next(status for status in statuses if status.value == "FAILED")] == set()
    assert ALLOWED_TRANSITIONS[next(status for status in statuses if status.value == "CANCELLED")] == set()


def test_different_active_reason_reuses_case_and_escalates_priority(phase3):
    first = _request(phase3, "risk-update", "EXPLICIT_HUMAN_REQUEST")
    second = _request(phase3, "risk-update", "SEVERE_ALLERGY")
    assert second["handoffId"] == first["handoffId"]
    assert second["reasonCode"] == "SEVERE_ALLERGY"
    assert second["priority"] == "CRITICAL"
    assert second["events"][-1]["eventType"] == "HANDOFF_RISK_UPDATED"


def test_summary_is_stable_for_unchanged_state(phase3):
    case = _request(phase3, "summary-stable")
    again = phase3.handoff_service.get(case["handoffId"])
    assert again["summaryVersion"] == 1
    assert again["summary"] == case["summary"]


class _BrokenSummary(HandoffSummaryService):
    def build(self, **_kwargs):
        raise RuntimeError("synthetic summary failure")


def test_summary_failure_keeps_diagnosable_failed_case(phase3):
    service = type(phase3.handoff_service)(
        phase3.uow_factory,
        phase3.tenant_service,
        phase3.handoff_provider,
        _BrokenSummary(),
    )
    state = phase3.session_store.get("summary-failure")
    record = phase3.safety_audit_service.evaluate_and_record(
        session_key="summary-failure",
        context=SafetyEvaluationContext(signals=frozenset({"SYSTEM_FAILURE"}), deterministic_input=True),
    )
    case = service.request_handoff(
        session_key="summary-failure",
        state=state,
        decision=record.decision,
        trace_id=record.trace_id,
    )
    assert case["status"] == "FAILED"
    assert case["failureCode"] == "SYSTEM_ERROR"
    assert case["summary"] is None


def test_concurrent_requests_converge_on_one_active_case(phase3):
    session_key = "concurrent-handoff"
    state = phase3.session_store.get(session_key)
    record = phase3.safety_audit_service.evaluate_and_record(
        session_key=session_key,
        context=SafetyEvaluationContext(signals=frozenset({"SEVERE_ALLERGY"}), deterministic_input=True),
    )

    def request_once():
        return phase3.handoff_service.request_handoff(
            session_key=session_key,
            state=state.clone(),
            decision=record.decision,
            trace_id=record.trace_id,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        cases = list(pool.map(lambda _index: request_once(), range(2)))
    assert len({case["handoffId"] for case in cases}) == 1
    with phase3.uow_factory() as uow:
        tenant = phase3.tenant_service.resolve()
        session = uow.sessions.get(session_key, tenant.restaurant_id, tenant.branch_id)
        active = uow.handoffs.get_active(session.id)
        assert active.public_id == cases[0]["handoffId"]
