from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import func, select

from app.db.models import ConversationContactSnapshot, ConversationSession, IdempotencyRecord, Order, OrderConfirmation
from app.domain.errors import DomainError
from app.state.session_state import OrderItem
from .conftest import make_context
from .helpers import persisted_state


def test_session_draft_survives_new_engine_and_store(phase2):
    state = persisted_state(phase2, "restart-draft")
    expected = state.serializable()
    second = make_context(phase2.database_url)
    try:
        restored = second.session_store.get("restart-draft")
        assert restored.serializable() == expected
    finally:
        second.database.engine.dispose()


def test_synthetic_contact_is_separated_from_ordinary_session_json(phase2):
    state = phase2.session_store.get("separate-contact")
    state.phone = "synthetic-phone-snapshot"
    state.official_delivery_address = "synthetic-address-snapshot"
    phase2.session_store.set("separate-contact", state)
    with phase2.database.session_factory() as session:
        row = session.scalar(select(ConversationSession).where(ConversationSession.session_key == "separate-contact"))
        contact = session.scalar(
            select(ConversationContactSnapshot).where(ConversationContactSnapshot.session_id == row.id)
        )
        assert "synthetic-phone-snapshot" not in str(row.state_json)
        assert "synthetic-address-snapshot" not in str(row.state_json)
        assert contact.phone == "synthetic-phone-snapshot"
        assert contact.official_delivery_address == "synthetic-address-snapshot"
        assert contact.is_synthetic is True
    restored = phase2.session_store.get("separate-contact")
    assert restored.phone == "synthetic-phone-snapshot"
    assert restored.official_delivery_address == "synthetic-address-snapshot"


def test_optimistic_concurrency_conflict_preserves_original_state(phase2):
    first = phase2.session_store.get("concurrent-session")
    second = phase2.session_store.get("concurrent-session")
    first.last_mentioned_item = "鸡腿饭"
    phase2.session_store.set("concurrent-session", first)
    stale_version = second.persistence_version
    second.last_mentioned_item = "牛肉饭"
    with pytest.raises(DomainError) as error:
        phase2.session_store.set("concurrent-session", second)
    assert error.value.code == "SESSION_VERSION_CONFLICT"
    assert second.persistence_version == stale_version
    assert phase2.session_store.get("concurrent-session").last_mentioned_item == "鸡腿饭"


def test_closed_session_cannot_be_modified_and_sessions_do_not_mix(phase2):
    one = phase2.session_store.get("session-one")
    two = phase2.session_store.get("session-two")
    one.last_mentioned_item = "鸡腿饭"
    phase2.session_store.set("session-one", one)
    assert phase2.session_store.get("session-two").last_mentioned_item is None
    phase2.session_store.reset("session-one")
    with pytest.raises(DomainError) as error:
        phase2.session_store.set("session-one", one)
    assert error.value.code == "SESSION_CLOSED"


def test_same_idempotency_key_and_fingerprint_returns_same_order(phase2):
    state = persisted_state(phase2, "idem-same")
    first = phase2.order_service.confirm_order(session_key="idem-same", state=state, idempotency_key="same-key")
    second = phase2.order_service.confirm_order(session_key="idem-same", state=state, idempotency_key="same-key")
    assert first.public_id == second.public_id
    assert first.idempotent_replay is False
    assert second.idempotent_replay is True
    with phase2.database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Order)) == 1
        assert session.scalar(select(func.count()).select_from(OrderConfirmation)) == 1
        assert session.scalar(select(func.count()).select_from(IdempotencyRecord)) == 1


def test_concurrent_same_request_creates_one_order_and_one_confirmation(phase2):
    state = persisted_state(phase2, "idem-concurrent")
    states = [state.clone(), state.clone()]
    barrier = Barrier(2)

    def confirm(copy):
        barrier.wait()
        return phase2.order_service.confirm_order(
            session_key="idem-concurrent",
            state=copy,
            idempotency_key="concurrent-key",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(confirm, states))
    assert results[0].public_id == results[1].public_id
    with phase2.database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Order)) == 1
        assert session.scalar(select(func.count()).select_from(OrderConfirmation)) == 1
        assert session.scalar(select(func.count()).select_from(IdempotencyRecord)) == 1


def test_same_idempotency_key_with_changed_request_conflicts(phase2):
    state = persisted_state(phase2, "idem-conflict")
    phase2.order_service.confirm_order(session_key="idem-conflict", state=state, idempotency_key="conflict-key")
    state.current_order[0].quantity = 2
    state.draft_version += 1
    phase2.session_store.set("idem-conflict", state)
    with pytest.raises(DomainError) as error:
        phase2.order_service.confirm_order(session_key="idem-conflict", state=state, idempotency_key="conflict-key")
    assert error.value.code == "IDEMPOTENCY_CONFLICT"


def test_idempotency_scope_does_not_cross_branch_or_restaurant(phase2):
    central = persisted_state(phase2, "idem-central", branch="central")
    east = persisted_state(phase2, "idem-east", branch="east")
    other_restaurant = persisted_state(
        phase2,
        "idem-other-restaurant",
        restaurant="hk-sim-restaurant-b",
        branch="north",
    )
    results = [
        phase2.order_service.confirm_order(session_key="idem-central", state=central, idempotency_key="shared-key"),
        phase2.order_service.confirm_order(
            session_key="idem-east", state=east, branch_code="east", idempotency_key="shared-key"
        ),
        phase2.order_service.confirm_order(
            session_key="idem-other-restaurant",
            state=other_restaurant,
            restaurant_code="hk-sim-restaurant-b",
            branch_code="north",
            idempotency_key="shared-key",
        ),
    ]
    assert len({result.public_id for result in results}) == 3


def test_another_sessions_draft_cannot_be_confirmed(phase2):
    owner = persisted_state(phase2, "confirmation-owner")
    phase2.session_store.get("confirmation-attacker")
    with pytest.raises(DomainError) as error:
        phase2.order_service.confirm_order(session_key="confirmation-attacker", state=owner)
    assert error.value.code == "CONFIRMATION_STALE"


def test_non_synthetic_order_state_is_rejected(phase2):
    state = persisted_state(phase2, "non-synthetic")
    state.is_synthetic = False
    with pytest.raises(DomainError) as error:
        phase2.order_service.confirm_order(session_key="non-synthetic", state=state)
    assert error.value.code == "SIMULATION_DATA_REQUIRED"
