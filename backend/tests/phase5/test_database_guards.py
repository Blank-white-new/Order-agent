from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.db.base import Base
from app.db.config import DatabaseSettings
from app.db.models import Order, SpeechTurnRecord
from app.db.session import create_database
from evaluation.phase5_harness import downgrade, migrate


def record(**changes) -> SpeechTurnRecord:
    values = {
        "public_id": f"SIM-ST-{uuid4().hex[:20].upper()}",
        "restaurant_id": 1,
        "branch_id": 1,
        "session_id": 1,
        "order_id": None,
        "direction": "INPUT",
        "provider_name": "replay",
        "provider_mode": "REPLAY",
        "audio_encoding": "WAV_PCM_S16LE",
        "sample_rate_hz": 16000,
        "duration_ms": 250,
        "audio_sha256": "a" * 64,
        "fixture_id": "synthetic-negative",
        "detected_locale": "zh-CN",
        "response_locale": "zh-CN",
        "confidence_bucket": "HIGH",
        "decision_classification": "AUTO_DRAFT",
        "reason_code": None,
        "outcome": "SUCCESS",
        "trace_id": "SIM-TRACE-NEGATIVE",
        "is_synthetic": True,
        "created_at": datetime.now(timezone.utc),
    }
    values.update(changes)
    return SpeechTurnRecord(**values)


@pytest.mark.parametrize(
    "changes",
    [
        {"direction": "SIDEWAYS"},
        {"provider_mode": "ONLINE"},
        {"outcome": "REAL_CALL"},
        {"is_synthetic": False},
        {"audio_sha256": "short"},
        {"sample_rate_hz": 0},
    ],
)
def test_database_rejects_invalid_direct_speech_writes(phase5, changes):
    session_key = f"phase5-db-{uuid4().hex}"
    phase5.text_entry.ensure_session_context(
        session_key,
        restaurant_code="hk-sim-restaurant-a",
        branch_code="central",
    )
    tenant = phase5.tenant_service.resolve("hk-sim-restaurant-a", "central")
    with phase5.uow_factory() as uow:
        session = uow.sessions.get(session_key, tenant.restaurant_id, tenant.branch_id)
        entity = record(
            restaurant_id=tenant.restaurant_id,
            branch_id=tenant.branch_id,
            session_id=session.id,
            **changes,
        )
        uow.speech.add(entity)
        with pytest.raises(IntegrityError):
            uow.flush()
        uow.rollback()


def test_cross_tenant_speech_write_is_rejected(phase5):
    session_key = f"phase5-cross-write-{uuid4().hex}"
    phase5.text_entry.ensure_session_context(
        session_key,
        restaurant_code="hk-sim-restaurant-a",
        branch_code="central",
    )
    tenant_a = phase5.tenant_service.resolve("hk-sim-restaurant-a", "central")
    tenant_b = phase5.tenant_service.resolve("hk-sim-restaurant-b", "harbor")
    with phase5.uow_factory() as uow:
        session = uow.sessions.get(session_key, tenant_a.restaurant_id, tenant_a.branch_id)
        uow.speech.add(
            record(
                restaurant_id=tenant_b.restaurant_id,
                branch_id=tenant_b.branch_id,
                session_id=session.id,
            )
        )
        with pytest.raises(IntegrityError):
            uow.flush()
        uow.rollback()


def test_cross_tenant_order_reference_is_rejected(phase5):
    session_a_key = f"phase5-order-a-{uuid4().hex}"
    session_b_key = f"phase5-order-b-{uuid4().hex}"
    phase5.text_entry.ensure_session_context(
        session_a_key,
        restaurant_code="hk-sim-restaurant-a",
        branch_code="central",
    )
    phase5.text_entry.ensure_session_context(
        session_b_key,
        restaurant_code="hk-sim-restaurant-b",
        branch_code="harbor",
    )
    tenant_a = phase5.tenant_service.resolve("hk-sim-restaurant-a", "central")
    tenant_b = phase5.tenant_service.resolve("hk-sim-restaurant-b", "harbor")
    with phase5.uow_factory() as uow:
        session_a = uow.sessions.get(session_a_key, tenant_a.restaurant_id, tenant_a.branch_id)
        uow.orders.add(
            Order(
                public_id=f"SIM-ORD-{uuid4().hex[:20].upper()}",
                restaurant_id=tenant_a.restaurant_id,
                branch_id=tenant_a.branch_id,
                session_id=session_a.id,
                status="DRAFT",
                draft_version=1,
                currency="HKD",
                subtotal_minor=0,
                delivery_fee_minor=0,
                total_minor=0,
                fulfillment_type="pickup",
                is_synthetic=True,
            )
        )
        uow.flush()
        order_id = uow.orders.get_latest_for_session(
            session_a.id,
            tenant_a.restaurant_id,
            tenant_a.branch_id,
        ).id
    with phase5.uow_factory() as uow:
        session_b = uow.sessions.get(session_b_key, tenant_b.restaurant_id, tenant_b.branch_id)
        uow.speech.add(
            record(
                restaurant_id=tenant_b.restaurant_id,
                branch_id=tenant_b.branch_id,
                session_id=session_b.id,
                order_id=order_id,
            )
        )
        with pytest.raises(IntegrityError):
            uow.flush()
        uow.rollback()


def test_duplicate_public_id_is_rejected_and_wrong_tenant_query_is_empty(phase5):
    session_key = f"phase5-duplicate-{uuid4().hex}"
    phase5.text_entry.ensure_session_context(
        session_key,
        restaurant_code="hk-sim-restaurant-a",
        branch_code="central",
    )
    tenant_a = phase5.tenant_service.resolve("hk-sim-restaurant-a", "central")
    tenant_b = phase5.tenant_service.resolve("hk-sim-restaurant-b", "harbor")
    public_id = f"SIM-ST-{uuid4().hex[:20].upper()}"
    with phase5.uow_factory() as uow:
        session = uow.sessions.get(session_key, tenant_a.restaurant_id, tenant_a.branch_id)
        first = record(
            public_id=public_id,
            restaurant_id=tenant_a.restaurant_id,
            branch_id=tenant_a.branch_id,
            session_id=session.id,
        )
        uow.speech.add(first)
    with phase5.uow_factory() as uow:
        assert uow.speech.get_scoped(public_id, tenant_b.restaurant_id, tenant_b.branch_id) is None
        session = uow.sessions.get(session_key, tenant_a.restaurant_id, tenant_a.branch_id)
        before = len(uow.speech.list_scoped(session.id, tenant_a.restaurant_id, tenant_a.branch_id))
        uow.speech.add(
            record(
                public_id=public_id,
                restaurant_id=tenant_a.restaurant_id,
                branch_id=tenant_a.branch_id,
                session_id=session.id,
            )
        )
        with pytest.raises(IntegrityError):
            uow.flush()
        uow.rollback()
    with phase5.uow_factory() as uow:
        session = uow.sessions.get(session_key, tenant_a.restaurant_id, tenant_a.branch_id)
        assert len(uow.speech.list_scoped(session.id, tenant_a.restaurant_id, tenant_a.branch_id)) == before


def test_phase5_migration_cycle_and_metadata_match(tmp_path):
    url = f"sqlite:///{(tmp_path / 'phase5-migration.db').as_posix()}"
    migrate(url, "20260718_0005")
    before = create_database(DatabaseSettings(app_env="test", database_url=url, auto_migrate_local=False))
    assert "speech_turn_records" not in inspect(before.engine).get_table_names()
    before.engine.dispose()
    migrate(url)
    upgraded = create_database(DatabaseSettings(app_env="test", database_url=url, auto_migrate_local=False))
    assert "speech_turn_records" in inspect(upgraded.engine).get_table_names()
    with upgraded.engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
    upgraded.engine.dispose()
    downgrade(url, "20260718_0005")
    downgraded = create_database(DatabaseSettings(app_env="test", database_url=url, auto_migrate_local=False))
    assert "speech_turn_records" not in inspect(downgraded.engine).get_table_names()
    downgraded.engine.dispose()
    migrate(url)
