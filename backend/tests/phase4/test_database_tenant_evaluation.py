from __future__ import annotations

import asyncio
from types import SimpleNamespace
import uuid

from sqlalchemy import func, select

from app.db.models import IdempotencyRecord, Order, OrderConfirmation
from evaluation.run_phase4_multilingual_text_eval import (
    audit_cross_tenant_data_access,
    database_snapshot,
)


TENANT = {"restaurant_code": "hk-sim-restaurant-a", "branch_code": "central"}


def test_phase4_confirmation_uses_real_sql_and_remains_idempotent(phase4):
    session_id = f"p4-db-idem-{uuid.uuid4().hex}"
    asyncio.run(
        phase4.text_entry.handle_text_message(
            session_id, "给我来两份鸡腿盖饭", **TENANT
        )
    )
    asyncio.run(
        phase4.text_entry.handle_text_message(session_id, "改成自取", **TENANT)
    )
    state = phase4.store.get(session_id, **TENANT)
    persistence = phase4.text_entry.order_persistence_service
    first = persistence.confirm_order(
        session_key=session_id,
        state=state,
        idempotency_key=f"p4-idem-{session_id}",
        **TENANT,
    )
    second = persistence.confirm_order(
        session_key=session_id,
        state=state,
        idempotency_key=f"p4-idem-{session_id}",
        **TENANT,
    )

    runtime = SimpleNamespace(database=phase4.database)
    counts = database_snapshot(runtime, session_id)
    assert first.public_id == second.public_id
    assert second.idempotent_replay is True
    assert counts == {
        "orders": 1,
        "active_confirmations": 1,
        "duplicate_active_confirmations": 0,
        "duplicate_idempotency_records": 0,
    }
    with phase4.database.session_factory() as session:
        session_row = session.scalar(
            select(Order).where(Order.public_id == first.public_id)
        )
        assert session_row is not None
        assert session.scalar(
            select(func.count()).select_from(OrderConfirmation).where(
                OrderConfirmation.order_id == session_row.id
            )
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(IdempotencyRecord).where(
                IdempotencyRecord.resource_id == first.public_id
            )
        ) == 1


def test_phase4_real_cross_tenant_access_audit(phase4):
    runtime = SimpleNamespace(
        database=phase4.database,
        service=phase4.text_entry,
        uow_factory=phase4.uow_factory,
        tenant_service=phase4.tenant_service,
        multilingual_service=phase4.text_entry.multilingual_text_service,
        handoff_service=phase4.text_entry.handoff_service,
    )

    metrics = asyncio.run(audit_cross_tenant_data_access(runtime))

    assert metrics.cross_tenant_data_access_checks == 10
    assert metrics.cross_tenant_data_leak_failures == 0
