from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from app.db.config import DatabaseSettings
from app.db.session import Database, create_database
from app.repositories.uow import SqlAlchemyUnitOfWork
from app.services.order_persistence_service import OrderPersistenceService
from app.services.seed_service import seed_phase2_simulation_data
from app.services.tenant_service import TenantService
from app.state.session_store import PersistentSessionStore


BACKEND_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Phase2Context:
    database: Database
    settings: DatabaseSettings
    uow_factory: object
    tenant_service: TenantService
    session_store: PersistentSessionStore
    order_service: OrderPersistenceService
    database_url: str


def migrate(database_url: str, revision: str = "head") -> None:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.attributes["skip_logging_config"] = True
    config.attributes["database_url"] = database_url
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, revision)


def downgrade(database_url: str, revision: str = "base") -> None:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.attributes["skip_logging_config"] = True
    config.attributes["database_url"] = database_url
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.downgrade(config, revision)


def make_context(database_url: str, *, seed: bool = True) -> Phase2Context:
    settings = DatabaseSettings(
        app_env="test",
        database_url=database_url,
        database_echo=False,
        auto_migrate_local=False,
        simulation_data_only=True,
        default_restaurant_code="hk-sim-restaurant-a",
        default_branch_code="central",
    )
    database = create_database(settings)
    migrate(database.settings.database_url)
    uow_factory = lambda: SqlAlchemyUnitOfWork(database.session_factory)
    if seed:
        seed_phase2_simulation_data(uow_factory)
    tenant_service = TenantService(uow_factory, database.settings)
    return Phase2Context(
        database=database,
        settings=database.settings,
        uow_factory=uow_factory,
        tenant_service=tenant_service,
        session_store=PersistentSessionStore(uow_factory, tenant_service),
        order_service=OrderPersistenceService(uow_factory, tenant_service, simulation_data_only=True),
        database_url=database.settings.database_url,
    )


@pytest.fixture
def phase2(tmp_path: Path):
    database_url = os.getenv("PHASE2_POSTGRES_URL") or f"sqlite:///{(tmp_path / 'phase2.db').as_posix()}"
    if database_url.startswith("postgresql"):
        downgrade(database_url)
    context = make_context(database_url)
    try:
        yield context
    finally:
        context.database.engine.dispose()
