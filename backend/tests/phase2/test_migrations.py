from __future__ import annotations

import os

import pytest
from sqlalchemy import inspect

from app.db.models import Base
from app.db.session import create_database
from app.db.config import DatabaseSettings
from .conftest import downgrade, make_context, migrate


EXPECTED_TABLES = set(Base.metadata.tables) | {"alembic_version"}


def test_sqlite_empty_upgrade_downgrade_reupgrade_and_schema_match(tmp_path):
    database_url = f"sqlite:///{(tmp_path / 'migration.db').as_posix()}"
    context = make_context(database_url, seed=False)
    inspector = inspect(context.database.engine)
    assert set(inspector.get_table_names()) == EXPECTED_TABLES
    assert {index["name"] for index in inspector.get_indexes("orders")} >= {
        "ix_orders_tenant_status",
        "ix_orders_session_created",
    }
    assert {constraint["name"] for constraint in inspector.get_unique_constraints("idempotency_records")} == {
        "uq_idempotency_tenant_scope_key"
    }
    context.database.engine.dispose()

    downgrade(database_url)
    empty = create_database(DatabaseSettings(app_env="test", database_url=database_url, auto_migrate_local=False))
    assert inspect(empty.engine).get_table_names() == ["alembic_version"]
    empty.engine.dispose()

    migrate(database_url)
    upgraded = create_database(DatabaseSettings(app_env="test", database_url=database_url, auto_migrate_local=False))
    assert set(inspect(upgraded.engine).get_table_names()) == EXPECTED_TABLES
    upgraded.engine.dispose()


def test_programmatic_migration_url_overrides_environment(monkeypatch, tmp_path):
    environment_path = tmp_path / "environment.db"
    requested_path = tmp_path / "requested.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{environment_path.as_posix()}")

    context = make_context(f"sqlite:///{requested_path.as_posix()}", seed=False)
    assert set(inspect(context.database.engine).get_table_names()) == EXPECTED_TABLES
    assert requested_path.is_file()
    assert not environment_path.exists()
    context.database.engine.dispose()


@pytest.mark.skipif(not os.getenv("PHASE2_POSTGRES_URL"), reason="PHASE2_POSTGRES_URL is provided by the PostgreSQL CI job")
def test_postgresql_empty_upgrade_downgrade_reupgrade():
    database_url = os.environ["PHASE2_POSTGRES_URL"]
    downgrade(database_url)
    context = make_context(database_url, seed=False)
    assert set(inspect(context.database.engine).get_table_names()) == EXPECTED_TABLES
    context.database.engine.dispose()
    downgrade(database_url)
    migrate(database_url)
    upgraded = create_database(DatabaseSettings(app_env="test", database_url=database_url, auto_migrate_local=False))
    assert set(inspect(upgraded.engine).get_table_names()) == EXPECTED_TABLES
    upgraded.engine.dispose()
