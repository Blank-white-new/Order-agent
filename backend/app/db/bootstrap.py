from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from threading import Lock

from alembic import command
from alembic.config import Config

from app.db.config import DatabaseSettings
from app.db.session import Database, create_database
from app.repositories.uow import SqlAlchemyUnitOfWork
from app.services.seed_service import seed_phase2_simulation_data
from app.services.phase4_menu_seed_service import Phase4MenuSeedService


_bootstrap_lock = Lock()
BACKEND_ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def get_runtime_database() -> Database:
    database = create_database()
    ensure_local_database(database)
    return database


def ensure_local_database(database: Database) -> None:
    settings = database.settings
    if not settings.may_auto_migrate:
        return
    with _bootstrap_lock:
        config = Config(str(BACKEND_ROOT / "alembic.ini"))
        config.attributes["skip_logging_config"] = True
        config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
        command.upgrade(config, "head")
        uow_factory = lambda: SqlAlchemyUnitOfWork(database.session_factory)
        seed_phase2_simulation_data(uow_factory)
        Phase4MenuSeedService(uow_factory).seed()


def initialize_database(database: Database, *, seed: bool = True) -> dict:
    if database.settings.app_env != "development" or not database.settings.is_sqlite:
        raise RuntimeError("Local automatic initialization is restricted to development SQLite.")
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.attributes["skip_logging_config"] = True
    config.set_main_option("sqlalchemy.url", database.settings.database_url.replace("%", "%%"))
    command.upgrade(config, "head")
    if not seed:
        return {}
    summary = seed_phase2_simulation_data(lambda: SqlAlchemyUnitOfWork(database.session_factory))
    uow_factory = lambda: SqlAlchemyUnitOfWork(database.session_factory)
    phase4 = Phase4MenuSeedService(uow_factory).seed()
    return {"phase2": summary.as_dict(), "phase4": phase4.as_dict()}
