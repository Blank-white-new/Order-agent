from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import HandoffCase, HandoffEvent
from tests.phase2.helpers import persisted_state


def _session_row(phase3, key: str, restaurant="hk-sim-restaurant-a", branch="central"):
    phase3.session_store.get(key, restaurant, branch)
    tenant = phase3.tenant_service.resolve(restaurant, branch)
    with phase3.uow_factory() as uow:
        row = uow.sessions.get(key, tenant.restaurant_id, tenant.branch_id)
        return row.id, tenant


def _case(**overrides):
    values = {
        "public_id": "SIM-HO-DB-GUARD",
        "restaurant_id": 1,
        "branch_id": 1,
        "session_id": 1,
        "order_id": None,
        "status": "REQUESTED",
        "reason_code": "SEVERE_ALLERGY",
        "priority": "CRITICAL",
        "decision_classification": "HANDOFF",
        "risk_ids_json": [],
        "blocked_actions_json": ["SUBMIT_TO_MERCHANT"],
        "summary_version": 1,
        "trace_id": "SIM-TRACE-DB-GUARD",
        "is_synthetic": True,
    }
    values.update(overrides)
    return HandoffCase(**values)


def test_database_rejects_cross_tenant_handoff_session(phase3):
    session_id, _tenant_a = _session_row(phase3, "db-cross-session")
    tenant_b = phase3.tenant_service.resolve("hk-sim-restaurant-b", "north")
    with phase3.database.session_factory() as session:
        session.add(
            _case(
                session_id=session_id,
                restaurant_id=tenant_b.restaurant_id,
                branch_id=tenant_b.branch_id,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


@pytest.mark.parametrize(
    ("override", "value"),
    [
        ("is_synthetic", False),
        ("status", "HUMAN_CONNECTED"),
        ("reason_code", "UNSTABLE_REASON"),
        ("decision_classification", "AUTO_SUBMIT"),
    ],
)
def test_database_rejects_non_synthetic_and_invalid_enums(phase3, override, value):
    session_id, tenant = _session_row(phase3, f"db-invalid-{override}")
    with phase3.database.session_factory() as session:
        session.add(
            _case(
                public_id=f"SIM-HO-{override.upper()}",
                session_id=session_id,
                restaurant_id=tenant.restaurant_id,
                branch_id=tenant.branch_id,
                **{override: value},
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_database_rejects_second_active_case_for_session(phase3):
    session_id, tenant = _session_row(phase3, "db-active-unique")
    with phase3.database.session_factory() as session:
        session.add_all(
            [
                _case(
                    public_id="SIM-HO-ACTIVE-1",
                    session_id=session_id,
                    restaurant_id=tenant.restaurant_id,
                    branch_id=tenant.branch_id,
                ),
                _case(
                    public_id="SIM-HO-ACTIVE-2",
                    session_id=session_id,
                    restaurant_id=tenant.restaurant_id,
                    branch_id=tenant.branch_id,
                    status="PENDING",
                ),
            ]
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_database_rejects_duplicate_event_sequence(phase3):
    session_id, tenant = _session_row(phase3, "db-event-sequence")
    with phase3.database.session_factory() as session:
        case = _case(
            public_id="SIM-HO-EVENT",
            session_id=session_id,
            restaurant_id=tenant.restaurant_id,
            branch_id=tenant.branch_id,
            status="FAILED",
        )
        session.add(case)
        session.flush()
        session.add_all(
            [
                HandoffEvent(
                    handoff_case_id=case.id,
                    sequence_number=1,
                    event_type="ONE",
                    actor_type="SYSTEM",
                    payload_json={},
                ),
                HandoffEvent(
                    handoff_case_id=case.id,
                    sequence_number=1,
                    event_type="TWO",
                    actor_type="SYSTEM",
                    payload_json={},
                ),
            ]
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_database_rejects_cross_tenant_handoff_order(phase3):
    order_state = persisted_state(phase3, "db-order-owner")
    order_result = phase3.order_service.confirm_order(
        session_key="db-order-owner", state=order_state, idempotency_key="db-order-owner-confirm"
    )
    session_b, tenant_b = _session_row(
        phase3,
        "db-order-other-tenant",
        "hk-sim-restaurant-b",
        "north",
    )
    tenant_a = phase3.tenant_service.resolve()
    with phase3.uow_factory() as uow:
        order = uow.orders.get_by_public_id(order_result.public_id, tenant_a.restaurant_id, tenant_a.branch_id)
        order_id = order.id
    with phase3.database.session_factory() as session:
        session.add(
            _case(
                public_id="SIM-HO-CROSS-ORDER",
                session_id=session_b,
                restaurant_id=tenant_b.restaurant_id,
                branch_id=tenant_b.branch_id,
                order_id=order_id,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
