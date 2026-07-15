from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.db.config import DatabaseSettings


@dataclass(frozen=True)
class Database:
    settings: DatabaseSettings
    engine: Engine
    session_factory: sessionmaker[Session]


def create_database(settings: DatabaseSettings | None = None) -> Database:
    settings = settings or DatabaseSettings.from_env()
    settings = replace(settings, database_url=_normalized_database_url(settings.database_url))
    if settings.is_sqlite:
        _ensure_sqlite_parent(settings.database_url)
    engine = create_engine(
        settings.database_url,
        echo=settings.database_echo,
        future=True,
        pool_pre_ping=True,
    )
    if settings.is_sqlite:
        @event.listens_for(engine, "connect")
        def _sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    return Database(
        settings=settings,
        engine=engine,
        session_factory=sessionmaker(bind=engine, expire_on_commit=False, autoflush=True, future=True),
    )


def _ensure_sqlite_parent(database_url: str) -> None:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return
    raw_path = database_url[len(prefix):]
    if raw_path in {"", ":memory:"} or raw_path.startswith("file:"):
        return
    Path(raw_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def _normalized_database_url(database_url: str) -> str:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return database_url
    raw_path = database_url[len(prefix):]
    if raw_path in {"", ":memory:"} or raw_path.startswith("file:"):
        return database_url
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return database_url
    project_root = Path(__file__).resolve().parents[3]
    return prefix + (project_root / path).resolve().as_posix()
