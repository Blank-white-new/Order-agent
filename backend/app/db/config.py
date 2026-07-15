from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values


TRUE_VALUES = {"1", "true", "yes", "on"}


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    return default if raw is None else raw.strip().lower() in TRUE_VALUES


@dataclass(frozen=True)
class DatabaseSettings:
    app_env: str = "development"
    database_url: str = "sqlite:///./.local-run/order-agent.db"
    database_echo: bool = False
    auto_migrate_local: bool = True
    simulation_data_only: bool = True
    default_restaurant_code: str = "hk-sim-restaurant-a"
    default_branch_code: str = "central"

    @classmethod
    def from_env(cls) -> "DatabaseSettings":
        env_file = os.getenv("BACKEND_ENV_FILE")
        if env_file is None:
            env_file = str(Path(__file__).resolve().parents[3] / ".env")
        file_values = dotenv_values(env_file) if Path(env_file).is_file() else {}

        def value(name: str, default: str) -> str:
            return str(os.getenv(name) if os.getenv(name) is not None else file_values.get(name, default) or default)

        def boolean(name: str, default: bool) -> bool:
            raw = os.getenv(name)
            if raw is None:
                raw = file_values.get(name)
            return default if raw is None else str(raw).strip().lower() in TRUE_VALUES

        return cls(
            app_env=value("APP_ENV", "development").strip().lower(),
            database_url=value("DATABASE_URL", "sqlite:///./.local-run/order-agent.db").strip(),
            database_echo=boolean("DATABASE_ECHO", False),
            auto_migrate_local=boolean("AUTO_MIGRATE_LOCAL", True),
            simulation_data_only=boolean("SIMULATION_DATA_ONLY", True),
            default_restaurant_code=value("DEFAULT_RESTAURANT_CODE", "hk-sim-restaurant-a").strip(),
            default_branch_code=value("DEFAULT_BRANCH_CODE", "central").strip(),
        )

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite:")

    @property
    def may_auto_migrate(self) -> bool:
        return self.app_env == "development" and self.is_sqlite and self.auto_migrate_local

    @property
    def safe_database_label(self) -> str:
        return "sqlite" if self.is_sqlite else self.database_url.split(":", 1)[0]
