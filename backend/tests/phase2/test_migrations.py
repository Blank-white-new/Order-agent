from __future__ import annotations

import os

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text

from app.db.models import Base
from app.db.session import create_database
from app.db.config import DatabaseSettings
from .conftest import downgrade, make_context, migrate


EXPECTED_TABLES = set(Base.metadata.tables) | {"alembic_version"}


def _assert_metadata_matches(engine) -> None:
    with engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []


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
    assert {constraint["name"] for constraint in inspector.get_unique_constraints("conversation_sessions")} >= {
        "uq_sessions_global_key",
        "uq_sessions_id_tenant",
    }
    assert {index["name"] for index in inspector.get_indexes("menu_versions")} >= {
        "uq_menu_versions_one_published_per_restaurant"
    }
    assert {constraint["name"] for constraint in inspector.get_foreign_keys("order_items")} >= {
        "fk_order_items_order_tenant",
        "fk_order_items_item_version",
        "fk_order_items_version_tenant",
    }
    _assert_metadata_matches(context.database.engine)
    context.database.engine.dispose()

    downgrade(database_url, "20260716_0002")
    previous = create_database(DatabaseSettings(app_env="test", database_url=database_url, auto_migrate_local=False))
    assert "restaurant_id" not in {column["name"] for column in inspect(previous.engine).get_columns("order_items")}
    previous.engine.dispose()

    migrate(database_url)
    upgraded = create_database(DatabaseSettings(app_env="test", database_url=database_url, auto_migrate_local=False))
    assert set(inspect(upgraded.engine).get_table_names()) == EXPECTED_TABLES
    _assert_metadata_matches(upgraded.engine)
    upgraded.engine.dispose()

    downgrade(database_url)
    empty = create_database(DatabaseSettings(app_env="test", database_url=database_url, auto_migrate_local=False))
    assert inspect(empty.engine).get_table_names() == ["alembic_version"]
    empty.engine.dispose()

    migrate(database_url)
    reupgraded = create_database(DatabaseSettings(app_env="test", database_url=database_url, auto_migrate_local=False))
    assert set(inspect(reupgraded.engine).get_table_names()) == EXPECTED_TABLES
    _assert_metadata_matches(reupgraded.engine)
    reupgraded.engine.dispose()


def test_programmatic_migration_url_overrides_environment(monkeypatch, tmp_path):
    environment_path = tmp_path / "environment.db"
    requested_path = tmp_path / "requested.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{environment_path.as_posix()}")

    context = make_context(f"sqlite:///{requested_path.as_posix()}", seed=False)
    assert set(inspect(context.database.engine).get_table_names()) == EXPECTED_TABLES
    assert requested_path.is_file()
    assert not environment_path.exists()
    context.database.engine.dispose()


def test_integrity_migration_refuses_duplicate_global_session_keys(tmp_path):
    database_url = f"sqlite:///{(tmp_path / 'conflicting-sessions.db').as_posix()}"
    migrate(database_url, "20260716_0002")
    database = create_database(
        DatabaseSettings(app_env="test", database_url=database_url, auto_migrate_local=False)
    )
    with database.engine.begin() as connection:
        for code in ["audit-a", "audit-b"]:
            connection.execute(
                text(
                    """
                    INSERT INTO restaurants
                        (code, name, status, default_locale, timezone, currency, is_simulation, created_at, updated_at)
                    VALUES
                        (:code, :name, 'ACTIVE', 'zh-CN', 'Asia/Hong_Kong', 'HKD', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """
                ),
                {"code": code, "name": f"Synthetic {code}"},
            )
        restaurants = {code: identifier for code, identifier in connection.execute(text("SELECT code, id FROM restaurants"))}
        for code, branch_code in [("audit-a", "one"), ("audit-b", "two")]:
            connection.execute(
                text(
                    """
                    INSERT INTO branches
                        (restaurant_id, code, name, timezone, status, active_menu_version_id, created_at, updated_at)
                    VALUES
                        (:restaurant_id, :code, :name, 'Asia/Hong_Kong', 'ACTIVE', NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """
                ),
                {
                    "restaurant_id": restaurants[code],
                    "code": branch_code,
                    "name": f"Synthetic {branch_code}",
                },
            )
        branches = {code: identifier for code, identifier in connection.execute(text("SELECT code, id FROM branches"))}
        for restaurant_code, branch_code in [("audit-a", "one"), ("audit-b", "two")]:
            connection.execute(
                text(
                    """
                    INSERT INTO conversation_sessions
                        (session_key, restaurant_id, branch_id, locale, state_json, version, status,
                         is_synthetic, created_at, updated_at)
                    VALUES
                        ('duplicate-audit-key', :restaurant_id, :branch_id, 'zh-CN', '{}', 1, 'ACTIVE',
                         1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """
                ),
                {
                    "restaurant_id": restaurants[restaurant_code],
                    "branch_id": branches[branch_code],
                },
            )
    database.engine.dispose()

    with pytest.raises(RuntimeError, match="duplicate conversation session_key"):
        migrate(database_url)

    database = create_database(
        DatabaseSettings(app_env="test", database_url=database_url, auto_migrate_local=False)
    )
    with database.engine.connect() as connection:
        assert MigrationContext.configure(connection).get_current_revision() == "20260716_0002"
    database.engine.dispose()


@pytest.mark.skipif(not os.getenv("PHASE2_POSTGRES_URL"), reason="PHASE2_POSTGRES_URL is provided by the PostgreSQL CI job")
def test_postgresql_empty_upgrade_downgrade_reupgrade():
    database_url = os.environ["PHASE2_POSTGRES_URL"]
    downgrade(database_url)
    context = make_context(database_url, seed=False)
    assert set(inspect(context.database.engine).get_table_names()) == EXPECTED_TABLES
    _assert_metadata_matches(context.database.engine)
    context.database.engine.dispose()

    downgrade(database_url, "20260716_0002")
    previous = create_database(DatabaseSettings(app_env="test", database_url=database_url, auto_migrate_local=False))
    assert "restaurant_id" not in {column["name"] for column in inspect(previous.engine).get_columns("order_items")}
    previous.engine.dispose()

    migrate(database_url)
    upgraded = create_database(DatabaseSettings(app_env="test", database_url=database_url, auto_migrate_local=False))
    assert set(inspect(upgraded.engine).get_table_names()) == EXPECTED_TABLES
    _assert_metadata_matches(upgraded.engine)
    upgraded.engine.dispose()
