from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import func, select

from app.agents.orchestrator import OrchestratorAgent
from app.db.models import (
    BranchItemAvailability,
    HandoffEvent,
    MenuItem,
    Order,
    OrderConfirmation,
    OrderEvent,
)
from app.domain.enums import HandoffFailureCode
from app.domain.errors import DomainError
from app.domain.safety import SafetyEvaluationContext
from app.services.text_entry_service import TextEntryService
from tests.phase2.helpers import persisted_state


def _request(phase3, session_key: str, reason: str):
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


def test_explicit_request_cancellation_preserves_unpersisted_draft(phase3):
    session_key = "cancel-explicit-draft"
    before = persisted_state(phase3, session_key).serializable()
    case = _request(phase3, session_key, "EXPLICIT_HUMAN_REQUEST")

    cancelled = phase3.handoff_service.cancel(case["handoffId"], None, None, session_key)

    assert cancelled["status"] == "CANCELLED"
    assert cancelled["mayContinueDraft"] is True
    assert cancelled["requiresNewConfirmation"] is True
    assert cancelled["safetyHoldActive"] is False
    restored = phase3.session_store.get(session_key)
    assert restored.serializable()["current_order"] == before["current_order"]
    assert restored.lifecycle_status == "DRAFT"
    assert restored.confirmation_valid is False
    with phase3.database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Order)) == 0


def test_confirmed_explicit_request_cancellation_requires_new_confirmation_without_duplicate_order(phase3):
    session_key = "cancel-explicit-confirmed"
    state = persisted_state(phase3, session_key)
    confirmed = phase3.order_service.confirm_order(
        session_key=session_key,
        state=state,
        idempotency_key="explicit-old-confirmation",
    )
    old_version = state.draft_version
    case = _request(phase3, session_key, "EXPLICIT_HUMAN_REQUEST")

    cancelled = phase3.handoff_service.cancel(case["handoffId"], None, None, session_key)

    assert cancelled["mayContinueDraft"] is True
    assert cancelled["safetyHoldCleared"] is True
    assert cancelled["confirmationRemainsInvalid"] is True
    assert cancelled["draftVersion"] == old_version + 1
    restored = phase3.session_store.get(session_key)
    assert restored.confirmation_valid is False
    assert restored.submitted is False
    assert restored.submitted_order_id is None
    assert restored.lifecycle_status == "DRAFT"
    assert restored.draft_version == old_version + 1

    with pytest.raises(DomainError) as replay_error:
        phase3.order_service.confirm_order(
            session_key=session_key,
            state=restored,
            idempotency_key="explicit-old-confirmation",
        )
    assert replay_error.value.code == "IDEMPOTENCY_CONFLICT"

    reconfirmed = phase3.order_service.confirm_order(
        session_key=session_key,
        state=restored,
        idempotency_key="explicit-new-confirmation",
    )
    assert reconfirmed.public_id == confirmed.public_id
    assert reconfirmed.lifecycle_status == "CUSTOMER_CONFIRMED"
    assert reconfirmed.merchant_status == "NOT_INTEGRATED"
    repeated_cancel = phase3.handoff_service.cancel(case["handoffId"], None, None, session_key)
    assert repeated_cancel["idempotentReplay"] is True
    assert repeated_cancel["requiresNewConfirmation"] is False
    assert repeated_cancel["confirmationRemainsInvalid"] is False
    assert phase3.session_store.get(session_key).confirmation_valid is True

    with phase3.database.session_factory() as session:
        order = session.scalar(select(Order).where(Order.public_id == confirmed.public_id))
        confirmations = list(
            session.scalars(
                select(OrderConfirmation)
                .where(OrderConfirmation.order_id == order.id)
                .order_by(OrderConfirmation.draft_version)
            )
        )
        event_types = set(
            session.scalars(select(OrderEvent.event_type).where(OrderEvent.order_id == order.id))
        )
        assert session.scalar(select(func.count()).select_from(Order)) == 1
        assert [confirmation.draft_version for confirmation in confirmations] == [old_version, old_version + 1]
        assert confirmations[0].invalidated_at is not None
        assert confirmations[1].invalidated_at is None
        assert order.safety_hold is False
        assert order.safety_hold_reason is None
        assert order.status == "CUSTOMER_CONFIRMED"
        assert not event_types.intersection({"ORDER_SUBMISSION_STARTED", "ORDER_MERCHANT_PENDING", "ORDER_MERCHANT_ACCEPTED"})


def test_reconfirmation_after_explicit_cancellation_rechecks_sold_out_state(phase3):
    session_key = "cancel-explicit-revalidate"
    state = persisted_state(phase3, session_key)
    phase3.order_service.confirm_order(session_key=session_key, state=state, idempotency_key="revalidate-old")
    case = _request(phase3, session_key, "EXPLICIT_HUMAN_REQUEST")
    phase3.handoff_service.cancel(case["handoffId"], None, None, session_key)
    restored = phase3.session_store.get(session_key)
    tenant = phase3.tenant_service.resolve()
    with phase3.database.session_factory() as session:
        item = session.scalar(select(MenuItem).where(MenuItem.code == "chicken_leg_rice"))
        availability = session.scalar(
            select(BranchItemAvailability).where(
                BranchItemAvailability.branch_id == tenant.branch_id,
                BranchItemAvailability.menu_item_id == item.id,
            )
        )
        availability.available = False
        availability.reason_code = "SYNTHETIC_TEST_SOLD_OUT"
        session.commit()

    with pytest.raises(DomainError) as error:
        phase3.order_service.confirm_order(
            session_key=session_key,
            state=restored,
            idempotency_key="revalidate-new",
        )
    assert error.value.code == "ITEM_SOLD_OUT"
    with phase3.database.session_factory() as session:
        order = session.scalar(select(Order))
        assert session.scalar(select(func.count()).select_from(Order)) == 1
        assert order.status == "DRAFT"
        assert order.safety_hold is False


@pytest.mark.parametrize("reason", ["SEVERE_ALLERGY", "CROSS_CONTAMINATION", "ABUSE_OR_SECURITY"])
def test_mandatory_cancellation_retains_hold_and_cannot_continue_or_confirm(phase3, reason):
    session_key = f"cancel-mandatory-{reason.lower()}"
    state = persisted_state(phase3, session_key)
    confirmed = phase3.order_service.confirm_order(session_key=session_key, state=state)
    case = _request(phase3, session_key, reason)

    cancelled = phase3.handoff_service.cancel(case["handoffId"], None, None, session_key)

    assert cancelled["status"] == "CANCELLED"
    assert cancelled["mayContinueDraft"] is False
    assert cancelled["safetyHoldCleared"] is False
    assert cancelled["safetyHoldActive"] is True
    restored = phase3.session_store.get(session_key)
    assert restored.safety_reason_code == reason
    assert restored.handoff_status == "CANCELLED"
    assert restored.confirmation_valid is False
    with pytest.raises(DomainError) as error:
        phase3.order_service.confirm_order(
            session_key=session_key,
            state=restored,
            idempotency_key=f"mandatory-new-{reason}",
        )
    assert error.value.code == "SAFETY_HOLD_ACTIVE"

    text_service = TextEntryService(
        store=phase3.session_store,
        orchestrator=OrchestratorAgent(),
        order_persistence_service=phase3.order_service,
        safety_audit_service=phase3.safety_audit_service,
        handoff_service=phase3.handoff_service,
    )
    continued = asyncio.run(text_service.handle_text_message(session_key, "继续自己下单"))
    assert continued["trace"]["safety"]["classification"] == "HANDOFF"
    assert continued["state"]["submitted"] is False
    assert continued["state"]["lifecycle_status"] == "DRAFT"

    with phase3.database.session_factory() as session:
        order = session.scalar(select(Order).where(Order.public_id == confirmed.public_id))
        assert session.scalar(select(func.count()).select_from(Order)) == 1
        assert order.status == "DRAFT"
        assert order.safety_hold is True
        assert order.safety_hold_reason == reason


@pytest.mark.parametrize(
    "failure_code",
    [
        HandoffFailureCode.NO_AGENT_AVAILABLE,
        HandoffFailureCode.QUEUE_TIMEOUT,
        HandoffFailureCode.CONNECTION_FAILED,
        HandoffFailureCode.SYSTEM_ERROR,
    ],
)
def test_failed_handoff_never_releases_hold_or_creates_fallback_order(phase3, failure_code):
    session_key = f"failed-handoff-{failure_code.value.lower()}"
    state = persisted_state(phase3, session_key)
    confirmed = phase3.order_service.confirm_order(session_key=session_key, state=state)
    case = _request(phase3, session_key, "SEVERE_ALLERGY")

    failed = phase3.handoff_service.simulate_fail(case["handoffId"], failure_code, None, None, session_key)

    assert failed["status"] == "FAILED"
    assert failed["failureCode"] == failure_code.value
    restored = phase3.session_store.get(session_key)
    with pytest.raises(DomainError) as error:
        phase3.order_service.confirm_order(
            session_key=session_key,
            state=restored,
            idempotency_key=f"failed-new-{failure_code.value}",
        )
    assert error.value.code == "SAFETY_HOLD_ACTIVE"
    with phase3.database.session_factory() as session:
        order = session.scalar(select(Order).where(Order.public_id == confirmed.public_id))
        confirmation = session.scalar(
            select(OrderConfirmation).where(
                OrderConfirmation.order_id == order.id,
                OrderConfirmation.draft_version == order.draft_version,
            )
        )
        assert session.scalar(select(func.count()).select_from(Order)) == 1
        assert order.safety_hold is True
        assert order.safety_hold_reason == "SEVERE_ALLERGY"
        assert order.status != "MERCHANT_ACCEPTED"
        assert confirmation.invalidated_at is not None
        assert restored.current_order


def test_cancellation_is_tenant_and_session_scoped_without_mutation(phase3):
    session_key = "cancel-owner"
    persisted_state(phase3, session_key)
    case = _request(phase3, session_key, "EXPLICIT_HUMAN_REQUEST")
    phase3.session_store.get("cancel-attacker")

    for restaurant, branch, owner in (
        ("hk-sim-restaurant-b", "north", session_key),
        (None, None, "cancel-attacker"),
    ):
        with pytest.raises(DomainError) as error:
            phase3.handoff_service.cancel(case["handoffId"], restaurant, branch, owner)
        assert error.value.code == "HANDOFF_NOT_FOUND"

    unchanged = phase3.handoff_service.get(case["handoffId"], None, None, session_key)
    assert unchanged["status"] == "PENDING"
    assert not any(event["eventType"] == "HANDOFF_CANCELLED" for event in unchanged["events"])


def test_concurrent_cancellation_has_one_transition_and_one_session_version_change(phase3):
    session_key = "cancel-concurrent"
    initial_state = persisted_state(phase3, session_key)
    initial_persistence_version = initial_state.persistence_version
    case = _request(phase3, session_key, "EXPLICIT_HUMAN_REQUEST")
    barrier = Barrier(2)

    def cancel_once():
        barrier.wait()
        return phase3.handoff_service.cancel(case["handoffId"], None, None, session_key)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: cancel_once(), range(2)))

    assert {result["status"] for result in results} == {"CANCELLED"}
    assert sorted(result["idempotentReplay"] for result in results) == [False, True]
    restored = phase3.session_store.get(session_key)
    assert restored.persistence_version == initial_persistence_version + 1
    with phase3.database.session_factory() as session:
        cancelled_events = session.scalar(
            select(func.count())
            .select_from(HandoffEvent)
            .where(HandoffEvent.event_type == "HANDOFF_CANCELLED")
        )
        assert cancelled_events == 1
        assert session.scalar(select(func.count()).select_from(Order)) == 0
