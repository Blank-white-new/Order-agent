from __future__ import annotations

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect

from app.db.models import Base
from app.db.session import create_database
from app.db.config import DatabaseSettings
from tests.phase2.conftest import downgrade, migrate


def _database(url: str):
    return create_database(DatabaseSettings(app_env="test", database_url=url, auto_migrate_local=False))


def test_phase2_head_upgrade_downgrade_and_reupgrade(tmp_path):
    url = f"sqlite:///{(tmp_path / 'phase2-to-phase3.db').as_posix()}"
    migrate(url, "20260717_0003")
    phase2 = _database(url)
    assert "handoff_cases" not in inspect(phase2.engine).get_table_names()
    phase2.engine.dispose()

    migrate(url)
    phase3 = _database(url)
    assert {"handoff_cases", "handoff_events", "safety_decision_records", "safety_session_counters"} <= set(
        inspect(phase3.engine).get_table_names()
    )
    with phase3.engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
    phase3.engine.dispose()

    downgrade(url, "20260717_0003")
    downgraded = _database(url)
    assert "handoff_cases" not in inspect(downgraded.engine).get_table_names()
    downgraded.engine.dispose()

    migrate(url)
    reupgraded = _database(url)
    with reupgraded.engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
    reupgraded.engine.dispose()
